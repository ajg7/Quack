import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.tools import ToolException

from quack import config, tracing
from quack.agent_lc import _extract_text, _report_errors_to_model
from quack.tracing_lc import TraceHandler, _is_partial


@pytest.fixture
def events(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path)

    def read():
        path = tmp_path / tracing.TRACE_FILE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    return read


def fake_llm_response(input_tokens=10, output_tokens=5, stop_reason="end_turn"):
    message = SimpleNamespace(
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens},
        response_metadata={"stop_reason": stop_reason},
    )
    return SimpleNamespace(generations=[[SimpleNamespace(message=message)]])


def test_extract_text_from_string():
    assert _extract_text("hello") == "hello"


def test_extract_text_skips_non_text_blocks():
    content = [
        {"type": "thinking", "thinking": "hmm", "signature": "x"},
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "world"},
    ]

    assert _extract_text(content) == "Hello world"


def test_is_partial_reads_flag_from_json_string():
    assert _is_partial(json.dumps({"results": [], "partial": True})) is True
    assert _is_partial(json.dumps({"results": [], "partial": False})) is False
    assert _is_partial("not json") is False
    assert _is_partial(None) is False


def test_report_errors_wraps_exceptions_as_tool_exception():
    def failing(**kwargs):
        raise RuntimeError("boom")

    with pytest.raises(ToolException, match="RuntimeError: boom"):
        _report_errors_to_model(failing)(query="x")


def test_report_errors_passes_results_through():
    assert _report_errors_to_model(lambda **kw: {"ok": kw})(a=1) == {"ok": {"a": 1}}


def test_handler_emits_claude_turn_and_accumulates_tokens(events):
    handler = TraceHandler("rid1")
    run_id = uuid4()

    handler.on_chat_model_start({}, [[]], run_id=run_id)
    handler.on_llm_end(fake_llm_response(100, 20, "tool_use"), run_id=run_id)

    turn = events()[0]
    assert turn["event"] == "claude_turn"
    assert turn["request_id"] == "rid1"
    assert turn["turn"] == 1
    assert turn["stop_reason"] == "tool_use"
    assert turn["input_tokens"] == 100
    assert turn["latency_ms"] is not None
    assert (handler.input_tokens, handler.output_tokens, handler.turns) == (100, 20, 1)


def test_handler_pairs_tool_start_and_end_by_run_id(events):
    handler = TraceHandler("rid2")
    first, second = uuid4(), uuid4()

    handler.on_tool_start({"name": "search_notion"}, "{'query': 'a'}", run_id=first, inputs={"query": "a"})
    handler.on_tool_start({"name": "search_notion"}, "{'query': 'b'}", run_id=second, inputs={"query": "b"})
    handler.on_tool_end(SimpleNamespace(content="{}", status="success"), run_id=second)
    handler.on_tool_end(SimpleNamespace(content='{"partial": true}', status="success"), run_id=first)

    by_query = {e["args"]["query"]: e for e in events()}
    assert by_query["b"]["partial"] is False
    assert by_query["a"]["partial"] is True
    assert by_query["a"]["tool"] == "search_notion"
    assert handler.tool_calls == 2


def test_handler_marks_tool_errors(events):
    handler = TraceHandler("rid3")
    run_id = uuid4()

    handler.on_tool_start({"name": "search_notion"}, "{}", run_id=run_id, inputs={})
    handler.on_tool_error(RuntimeError("boom"), run_id=run_id)

    call = events()[0]
    assert call["is_error"] is True
    assert call["output_chars"] == len("RuntimeError: boom")


def test_handler_ignores_tool_end_without_start(events):
    handler = TraceHandler("rid4")

    handler.on_tool_end(SimpleNamespace(content="x", status="success"), run_id=uuid4())

    assert events() == []
