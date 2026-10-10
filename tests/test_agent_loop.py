import json
import threading
from types import SimpleNamespace

import pytest

from quack import agent, config, tools, tracing


def text(content):
    return SimpleNamespace(type="text", text=content)


def tool_use(tool_id, name="search_notion", **args):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)


def response(blocks, stop_reason):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        reply = self.replies.pop(0)
        return reply(kwargs) if callable(reply) else reply


@pytest.fixture
def traced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path)

    def read():
        path = tmp_path / tracing.TRACE_FILE
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    return read


def use_client(monkeypatch, replies):
    client = FakeClient(replies)
    monkeypatch.setattr(config, "anthropic_client", lambda: client)
    return client


def test_plain_answer_needs_no_tools(monkeypatch, traced):
    use_client(monkeypatch, [response([text("hi")], "end_turn")])

    assert agent.ask("hello") == "hi"

    end = traced()[-1]
    assert end["event"] == "question_end"
    assert end["tool_steps"] == 0
    assert end["budget_exhausted"] is None


def test_tool_results_go_back_to_the_model(monkeypatch, traced):
    monkeypatch.setitem(tools.HANDLERS, "search_notion", lambda **kw: {"echo": kw["query"]})
    client = use_client(
        monkeypatch,
        [
            response([tool_use("t1", query="agoge")], "tool_use"),
            response([text("done")], "end_turn"),
        ],
    )

    assert agent.ask("q") == "done"

    sent = client.calls[1]["messages"][-1]["content"][0]
    assert sent["tool_use_id"] == "t1"
    assert json.loads(sent["content"]) == {"echo": "agoge"}
    assert "is_error" not in sent


def test_handler_errors_are_reported_to_the_model(monkeypatch, traced):
    def boom(**kw):
        raise RuntimeError("nope")

    monkeypatch.setitem(tools.HANDLERS, "search_notion", boom)
    client = use_client(
        monkeypatch,
        [response([tool_use("t1", query="x")], "tool_use"), response([text("sorry")], "end_turn")],
    )

    agent.ask("q")

    sent = client.calls[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True
    assert "RuntimeError: nope" in sent["content"]


def test_parallel_tool_calls_run_concurrently_and_keep_order(monkeypatch, traced):
    barrier = threading.Barrier(2, timeout=5)

    def meet(**kw):
        barrier.wait()
        return {"id": kw["query"]}

    monkeypatch.setitem(tools.HANDLERS, "search_notion", meet)
    client = use_client(
        monkeypatch,
        [
            response([tool_use("a", query="one"), tool_use("b", query="two")], "tool_use"),
            response([text("ok")], "end_turn"),
        ],
    )

    assert agent.ask("q") == "ok"

    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert [json.loads(r["content"])["id"] for r in results] == ["one", "two"]


def test_step_budget_turns_calls_into_errors_then_forces_an_answer(monkeypatch, traced):
    monkeypatch.setattr(config, "MAX_TOOL_STEPS", 1)
    monkeypatch.setitem(tools.HANDLERS, "search_notion", lambda **kw: {"ok": True})
    client = use_client(
        monkeypatch,
        [
            response([tool_use("a", query="1")], "tool_use"),
            response([tool_use("b", query="2")], "tool_use"),
            response([text("partial answer")], "end_turn"),
        ],
    )

    assert agent.ask("q") == "partial answer"

    second_results = client.calls[2]["messages"][-1]["content"]
    assert second_results[0]["is_error"] is True
    assert "Budget exhausted" in second_results[0]["content"]
    assert "tool_choice" not in client.calls[0]
    assert "tool_choice" not in client.calls[1]
    assert client.calls[2]["tool_choice"] == {"type": "none"}
    end = traced()[-1]
    assert end["budget_exhausted"] == "steps"
    assert end["tool_steps"] == 1


def test_turn_cap_forces_a_final_answer_even_without_budget_errors(monkeypatch, traced):
    monkeypatch.setattr(config, "MAX_TOOL_STEPS", 1)
    monkeypatch.setattr(config, "FINAL_ANSWER_GRACE_TURNS", 0)
    monkeypatch.setitem(tools.HANDLERS, "search_notion", lambda **kw: {"ok": True})
    client = use_client(
        monkeypatch,
        [
            response([tool_use("a", query="1")], "tool_use"),
            response([text("final")], "end_turn"),
        ],
    )

    assert agent.ask("q") == "final"

    assert client.calls[1]["tool_choice"] == {"type": "none"}


def test_tool_call_trace_carries_request_and_cache_counts(monkeypatch, traced):
    def spend(**kw):
        agent.budget.charge_request()
        agent.budget.note_cache_hit()
        return {"partial": False}

    monkeypatch.setitem(tools.HANDLERS, "search_notion", spend)
    use_client(
        monkeypatch,
        [response([tool_use("a", query="1")], "tool_use"), response([text("ok")], "end_turn")],
    )

    agent.ask("q")

    call = next(e for e in traced() if e["event"] == "tool_call")
    assert call["notion_requests"] == 1
    assert call["cache_hits"] == 1
    assert call["is_error"] is False
    assert traced()[-1]["notion_requests"] == 1
