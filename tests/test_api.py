import json

import pytest
from fastapi.testclient import TestClient

from quack import api, config
from quack.integrations.notion import NotionResults
from quack.sessions import SessionStore
from quack.tools import notion as notion_tools_module


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "sessions", SessionStore())
    return TestClient(api.app)


def fake_stream(answer="the answer", calls=None):
    def stream(question, history=None, model=None):
        if calls is not None:
            calls.append({"question": question, "history": history, "model": model})
        yield {"event": "start", "data": {"request_id": "r1"}}
        yield {"event": "progress", "data": {"status": "start", "step": 1, "tool": "search_notion", "message": "m"}}
        yield {"event": "token", "data": {"text": "the "}}
        yield {"event": "token", "data": {"text": "answer"}}
        yield {"event": "done", "data": {"answer": answer, "request_id": "r1"}}

    return stream


def test_format_sse_shape():
    text = api.format_sse({"event": "token", "data": {"text": "héllo"}})

    assert text == 'event: token\ndata: {"text": "héllo"}\n\n'


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": config.MODEL}


def test_models_lists_choices_with_opus_default(client):
    body = client.get("/models").json()

    assert body["default"] == "claude-opus-5-5"
    assert [m["id"] for m in body["models"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]


def test_chat_passes_selected_model_to_the_stream(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream(calls=calls))

    client.post("/chat", json={"session_id": "s", "message": "hi", "model": "claude-sonnet-5-5"})

    assert calls[0]["model"] == "claude-sonnet-5-5"


def test_chat_defaults_to_opus_when_model_is_omitted(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream(calls=calls))

    client.post("/chat", json={"session_id": "s", "message": "hi"})

    assert calls[0]["model"] == config.MODEL


def test_chat_rejects_an_unknown_model(client, monkeypatch):
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream())

    response = client.post("/chat", json={"session_id": "s", "message": "hi", "model": "gpt-4"})

    assert response.status_code == 422


def test_chat_streams_events_as_sse(client, monkeypatch):
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream())

    response = client.post("/chat", json={"session_id": "s", "message": "hi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "progress", "token", "token", "done"]
    assert events[-1][1]["answer"] == "the answer"


def test_chat_remembers_turns_within_a_session(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream("first answer", calls))

    client.post("/chat", json={"session_id": "s", "message": "first question"})
    client.post("/chat", json={"session_id": "s", "message": "second question"})

    assert calls[0]["history"] == []
    assert calls[1]["history"] == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_chat_sessions_do_not_share_history(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream("a", calls))

    client.post("/chat", json={"session_id": "one", "message": "q"})
    client.post("/chat", json={"session_id": "two", "message": "q"})

    assert calls[1]["history"] == []


def test_failed_run_is_not_added_to_history(client, monkeypatch):
    def failing(question, history=None, model=None):
        yield {"event": "start", "data": {"request_id": "r"}}
        yield {"event": "error", "data": {"message": "RuntimeError: boom", "request_id": "r"}}

    monkeypatch.setattr(api.streaming, "stream_events", failing)

    response = client.post("/chat", json={"session_id": "s", "message": "q"})

    assert [name for name, _ in parse_sse(response.text)] == ["start", "error"]
    assert api.sessions.get("s") == []


@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "s", "message": ""},
        {"session_id": "", "message": "hi"},
        {"message": "hi"},
        {"session_id": "s"},
        {"session_id": "s", "message": "x" * 8001},
        {"session_id": "s" * 129, "message": "hi"},
    ],
)
def test_chat_rejects_invalid_bodies(client, body):
    assert client.post("/chat", json=body).status_code == 422


def test_delete_session_clears_history(client, monkeypatch):
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream())
    client.post("/chat", json={"session_id": "s", "message": "q"})

    assert client.delete("/sessions/s").json() == {"cleared": True}
    assert client.delete("/sessions/s").json() == {"cleared": False}
    assert api.sessions.get("s") == []


def test_cors_allows_the_vite_dev_origin(client):
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_other_origins(client):
    response = client.options(
        "/chat",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_sources_lists_data_sources_sorted_by_name(client, monkeypatch):
    items = [
        {"object": "data_source", "id": "b", "title": [{"plain_text": "Odysseys"}]},
        {"object": "data_source", "id": "a", "title": [{"plain_text": "agoge"}]},
    ]
    monkeypatch.setattr(
        notion_tools_module.notion, "search", lambda query, filters=None: NotionResults(items)
    )

    response = client.get("/sources")

    assert response.status_code == 200
    assert response.json() == {
        "sources": [{"id": "a", "name": "agoge"}, {"id": "b", "name": "Odysseys"}],
        "partial": False,
    }


def test_sources_asks_notion_for_data_sources_only(client, monkeypatch):
    seen = {}

    def fake_search(query, filters=None):
        seen["args"] = (query, filters)
        return NotionResults([])

    monkeypatch.setattr(notion_tools_module.notion, "search", fake_search)

    client.get("/sources")

    assert seen["args"] == ("", {"property": "object", "value": "data_source"})


def test_sources_reports_partial_results(client, monkeypatch):
    monkeypatch.setattr(
        notion_tools_module.notion,
        "search",
        lambda query, filters=None: NotionResults([], partial=True),
    )

    assert client.get("/sources").json()["partial"] is True


def test_sources_failure_becomes_502(client, monkeypatch):
    def boom(query, filters=None):
        raise RuntimeError("Notion exploded")

    monkeypatch.setattr(notion_tools_module.notion, "search", boom)

    response = client.get("/sources")

    assert response.status_code == 502
    assert "Notion exploded" in response.json()["detail"]


def test_second_question_in_a_busy_session_is_rejected_with_409(client):
    api.sessions.try_begin_turn("busy")

    response = client.post("/chat", json={"session_id": "busy", "message": "q"})

    assert response.status_code == 409


def test_turn_lock_is_released_after_the_stream_ends(client, monkeypatch):
    monkeypatch.setattr(api.streaming, "stream_events", fake_stream())

    client.post("/chat", json={"session_id": "s", "message": "q"})

    assert api.sessions.try_begin_turn("s") is True
