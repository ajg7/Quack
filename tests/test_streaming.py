import queue
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quack import agent_lc, config, streaming
from quack.streaming import StreamCancelled, StreamHandler, describe_tool_call, stream_events


def make_result(answer="done"):
    return agent_lc.RunResult(
        answer=answer,
        request_id="rid",
        turns=1,
        tool_calls=0,
        input_tokens=10,
        output_tokens=5,
        latency_ms=7,
    )


def chunk(content):
    return SimpleNamespace(message=SimpleNamespace(content=content))


def drain(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


def test_describe_search_includes_the_query():
    assert describe_tool_call("search_notion", {"query": "Agoge"}) == 'Searching Notion for "Agoge"'


def test_describe_query_mentions_filter_only_when_present():
    assert describe_tool_call("query_database", {"filter": {"a": 1}}) == "Querying a database with a filter"
    assert describe_tool_call("query_database", {}) == "Querying a database"


def test_describe_get_page_and_unknown_tools():
    assert describe_tool_call("get_page", {"page_id": "x"}) == "Reading a page"
    assert describe_tool_call("mystery", None) == "Running mystery"


def test_handler_streams_text_blocks_only():
    q = queue.Queue()
    handler = StreamHandler(q, threading.Event())

    handler.on_llm_new_token("ignored", chunk=chunk([{"type": "text", "text": "Hel"}]))
    handler.on_llm_new_token("ignored", chunk=chunk([{"type": "thinking", "thinking": "hmm"}]))
    handler.on_llm_new_token("ignored", chunk=chunk([{"type": "input_json_delta", "partial_json": "{"}]))
    handler.on_llm_new_token("ignored", chunk=chunk("lo"))
    handler.on_llm_new_token("ignored", chunk=None)

    assert [e["data"]["text"] for e in drain(q)] == ["Hel", "lo"]


def test_handler_numbers_tool_steps_and_reports_completion():
    q = queue.Queue()
    handler = StreamHandler(q, threading.Event())
    first, second = uuid4(), uuid4()

    handler.on_tool_start({"name": "search_notion"}, "", run_id=first, inputs={"query": "x"})
    handler.on_tool_end(SimpleNamespace(status="success"), run_id=first)
    handler.on_tool_start({"name": "get_page"}, "", run_id=second, inputs={"page_id": "p"})
    handler.on_tool_error(RuntimeError("boom"), run_id=second)

    events = [e["data"] for e in drain(q)]
    assert [(e["step"], e["status"]) for e in events] == [(1, "start"), (1, "done"), (2, "start"), (2, "error")]
    assert events[0]["message"] == 'Searching Notion for "x"'
    assert events[0]["args"] == {"query": "x"}


def test_handler_flags_tool_message_errors():
    q = queue.Queue()
    handler = StreamHandler(q, threading.Event())
    run_id = uuid4()

    handler.on_tool_start({"name": "query_database"}, "", run_id=run_id, inputs={})
    handler.on_tool_end(SimpleNamespace(status="error"), run_id=run_id)

    assert drain(q)[-1]["data"]["status"] == "error"


def test_handler_ignores_tool_end_without_start():
    q = queue.Queue()
    handler = StreamHandler(q, threading.Event())

    handler.on_tool_end(SimpleNamespace(status="success"), run_id=uuid4())

    assert drain(q) == []


def test_handler_raises_once_cancelled():
    cancelled = threading.Event()
    handler = StreamHandler(queue.Queue(), cancelled)
    cancelled.set()

    with pytest.raises(StreamCancelled):
        handler.on_llm_new_token("x", chunk=chunk("x"))
    with pytest.raises(StreamCancelled):
        handler.on_tool_start({"name": "t"}, "", run_id=uuid4(), inputs={})


def test_stream_events_orders_start_progress_token_done(monkeypatch):
    def fake_run(question, history, handlers, request_id):
        handler = handlers[0]
        handler.on_tool_start({"name": "search_notion"}, "", run_id=uuid4(), inputs={"query": question})
        handler.on_llm_new_token("x", chunk=chunk([{"type": "text", "text": "hi"}]))
        return make_result("hi")

    monkeypatch.setattr(agent_lc, "run", fake_run)

    names = [e["event"] for e in stream_events("Agoge")]

    assert names == ["start", "progress", "token", "done"]


def test_stream_events_done_carries_usage_and_answer(monkeypatch):
    monkeypatch.setattr(agent_lc, "run", lambda *a, **k: make_result("final"))

    done = list(stream_events("q"))[-1]

    assert done["event"] == "done"
    assert done["data"]["answer"] == "final"
    assert done["data"]["input_tokens"] == 10
    assert done["data"]["latency_ms"] == 7


def test_stream_events_passes_history_through(monkeypatch):
    seen = {}

    def fake_run(question, history, handlers, request_id):
        seen["history"] = history
        seen["request_id"] = request_id
        return make_result()

    monkeypatch.setattr(agent_lc, "run", fake_run)
    history = [{"role": "user", "content": "earlier"}]

    events = list(stream_events("q", history))

    assert seen["history"] == history
    assert events[0]["data"]["request_id"] == seen["request_id"]


def test_stream_events_turns_exceptions_into_an_error_event(monkeypatch):
    def fake_run(*args, **kwargs):
        raise RuntimeError("Notion exploded")

    monkeypatch.setattr(agent_lc, "run", fake_run)

    events = list(stream_events("q"))

    assert [e["event"] for e in events] == ["start", "error"]
    assert "Notion exploded" in events[-1]["data"]["message"]
    assert events[-1]["data"]["request_id"] == events[0]["data"]["request_id"]


def test_stream_events_truncates_long_error_messages(monkeypatch):
    def fake_run(*args, **kwargs):
        raise RuntimeError("x" * 5000)

    monkeypatch.setattr(agent_lc, "run", fake_run)

    error = list(stream_events("q"))[-1]

    assert len(error["data"]["message"]) <= 300


def test_stream_events_emits_pings_while_waiting(monkeypatch):
    release = threading.Event()

    def slow_run(*args, **kwargs):
        release.wait(timeout=5)
        return make_result()

    monkeypatch.setattr(agent_lc, "run", slow_run)
    monkeypatch.setattr(config, "SSE_KEEPALIVE_SECONDS", 0.05)

    stream = stream_events("q")
    assert next(stream)["event"] == "start"
    assert next(stream)["event"] == "ping"
    release.set()

    assert [e["event"] for e in stream] == ["done"]


def test_closing_the_stream_cancels_the_worker(monkeypatch):
    cancelled_seen = threading.Event()

    def fake_run(question, history, handlers, request_id):
        handler = handlers[0]
        try:
            for _ in range(200):
                handler.on_llm_new_token("x", chunk=chunk("t"))
                time.sleep(0.01)
        except StreamCancelled:
            cancelled_seen.set()
            raise
        return make_result()

    monkeypatch.setattr(agent_lc, "run", fake_run)

    stream = stream_events("q")
    next(stream)
    next(stream)
    stream.close()

    assert cancelled_seen.wait(timeout=3)


def test_module_exposes_the_sentinel_without_leaking_it(monkeypatch):
    monkeypatch.setattr(agent_lc, "run", lambda *a, **k: make_result())

    assert streaming._DONE not in list(stream_events("q"))
