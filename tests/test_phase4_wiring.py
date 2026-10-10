import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from quack import agent_lc, api, budget, config, router, tools, tracing
from quack.integrations import notion
from quack.retrieval import indexer
from quack.tools import semantic
from quack.tracing_lc import TraceHandler, route_of


class FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    class NoLimiter:
        def acquire(self):
            pass

    monkeypatch.setattr(notion, "_limiter", NoLimiter())
    monkeypatch.setattr(config, "notion_headers", lambda: {})
    notion.clear_cache()
    yield
    notion.clear_cache()


def test_search_edited_since_sorts_newest_first_and_stops_at_the_checkpoint(monkeypatch):
    bodies = []
    pages = [
        {"id": "c", "last_edited_time": "2026-03"},
        {"id": "b", "last_edited_time": "2026-02"},
        {"id": "a", "last_edited_time": "2026-01"},
    ]

    def fake(method, url, **kwargs):
        bodies.append(kwargs["json"])
        return FakeResponse({"results": pages, "has_more": True, "next_cursor": "next"})

    monkeypatch.setattr(notion.requests, "request", fake)

    found = notion.search_edited_since("2026-02")

    assert [p["id"] for p in found.results] == ["c", "b"]
    assert found.has_more is False
    assert len(bodies) == 1
    assert bodies[0]["sort"] == {"direction": "descending", "timestamp": "last_edited_time"}
    assert bodies[0]["filter"] == {"property": "object", "value": "page"}


def test_search_edited_since_without_checkpoint_reads_every_page(monkeypatch):
    responses = [
        FakeResponse({"results": [{"id": "b", "last_edited_time": "2"}], "has_more": True, "next_cursor": "n"}),
        FakeResponse({"results": [{"id": "a", "last_edited_time": "1"}], "has_more": False}),
    ]
    monkeypatch.setattr(notion.requests, "request", lambda *a, **k: responses.pop(0))

    assert [p["id"] for p in notion.search_edited_since().results] == ["b", "a"]


def test_fresh_requests_skip_the_cache_but_refill_it(monkeypatch):
    calls = []

    def fake(method, url, **kwargs):
        calls.append(url)
        return FakeResponse({"n": len(calls)})

    monkeypatch.setattr(notion.requests, "request", fake)

    assert notion.get_page("p")["n"] == 1
    assert notion.get_page("p")["n"] == 1
    assert notion.get_page("p", fresh=True)["n"] == 2
    assert notion.get_page("p")["n"] == 2
    assert len(calls) == 2


def test_semantic_search_tool_delegates_to_the_router(monkeypatch):
    seen = {}
    monkeypatch.setattr(router, "semantic_search", lambda q, limit: seen.update(q=q, limit=limit) or {"ok": 1})

    assert semantic.semantic_search("tenses", 3) == {"ok": 1}
    assert seen == {"q": "tenses", "limit": 3}


def test_semantic_search_is_registered_with_its_own_route():
    assert "semantic_search" in tools.HANDLERS
    assert router.TOOL_ROUTES["semantic_search"] == router.RAG
    assert set(router.TOOL_ROUTES) == set(tools.HANDLERS)


def test_route_of_reads_a_fallback_route_from_tool_output():
    payload = json.dumps({"route": router.LIVE_FALLBACK})

    assert route_of("semantic_search", payload) == router.LIVE_FALLBACK
    assert route_of("semantic_search", "not json") == router.RAG
    assert route_of("query_database", None) == router.LIVE


def test_trace_handler_logs_the_route_on_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path)
    handler = TraceHandler("req1")
    run_id = "00000000-0000-0000-0000-000000000001"

    handler.on_tool_start({"name": "semantic_search"}, "", run_id=run_id, inputs={"query": "q"})
    handler.on_tool_end(SimpleNamespace(content=json.dumps({"route": "rag"}), status="success"), run_id=run_id)

    event = json.loads((tmp_path / tracing.TRACE_FILE).read_text(encoding="utf-8").splitlines()[0])
    assert event["route"] == "rag"
    assert event["tool"] == "semantic_search"


def call_middleware(messages):
    seen = {}

    class Request:
        def __init__(self, tool_choice=None):
            self.messages = messages
            self.tool_choice = tool_choice

        def override(self, **changes):
            return Request(changes.get("tool_choice", self.tool_choice))

    def handler(request):
        seen["tool_choice"] = request.tool_choice
        return "response"

    result = agent_lc.answer_when_out_of_budget.wrap_model_call(Request(), handler)
    return result, seen["tool_choice"]


def test_langchain_model_calls_are_unrestricted_within_budget():
    with budget.activate(budget.Budget()):
        _, tool_choice = call_middleware([HumanMessage("q")])

    assert tool_choice is None


def test_langchain_model_calls_must_answer_once_the_budget_is_spent():
    with budget.activate(budget.Budget(max_steps=0)) as active:
        with pytest.raises(budget.BudgetExceeded):
            active.charge_step()
        _, tool_choice = call_middleware([HumanMessage("q")])

    assert tool_choice == {"type": "none"}


def test_langchain_model_calls_must_answer_after_the_turn_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_STEPS", 1)
    monkeypatch.setattr(config, "FINAL_ANSWER_GRACE_TURNS", 0)

    with budget.activate(budget.Budget()):
        _, tool_choice = call_middleware([HumanMessage("q"), AIMessage("calling a tool")])

    assert tool_choice == {"type": "none"}


@pytest.fixture
def client(monkeypatch, fake_store, tmp_path):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path)
    monkeypatch.setattr(api, "get_store", lambda: fake_store)
    return TestClient(api.app)


def test_index_endpoint_reports_stats_and_checkpoint(client, fake_store):
    fake_store.replace_page("p1", "T", "u", "2026-01", ["a", "b"])
    indexer.save_checkpoint("2026-01")

    body = client.get("/index").json()

    assert body == {"available": True, "chunks": 2, "pages": 1, "checkpoint": "2026-01"}


def test_index_endpoint_degrades_when_the_index_is_unavailable(client, fake_store):
    fake_store.fail = "gone"

    body = client.get("/index").json()

    assert body == {"available": False, "chunks": 0, "pages": 0, "checkpoint": None}
