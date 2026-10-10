import json
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from quack import budget, router, tracing


def _is_partial(content: Any) -> bool:
    if not isinstance(content, str):
        return False
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("partial"))


def route_of(tool: str | None, content: Any) -> str:
    result = None
    if isinstance(content, str):
        try:
            result = json.loads(content)
        except ValueError:
            result = None
    return router.route_for(tool or "", result)


class TraceHandler(BaseCallbackHandler):
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.turns = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._model_starts: dict[UUID, float] = {}
        self._tool_runs: dict[UUID, dict[str, Any]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, **kwargs) -> None:
        self._model_starts[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id: UUID, **kwargs) -> None:
        started = self._model_starts.pop(run_id, None)
        message = getattr(response.generations[0][0], "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}

        self.turns += 1
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)

        tracing.emit(
            "claude_turn",
            self.request_id,
            turn=self.turns,
            stop_reason=metadata.get("stop_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=round((time.perf_counter() - started) * 1000) if started else None,
        )

    def on_tool_start(
        self, serialized, input_str, *, run_id: UUID, inputs: dict | None = None, **kwargs
    ) -> None:
        self.tool_calls += 1
        self._tool_runs[run_id] = {
            "tool": (serialized or {}).get("name") or kwargs.get("name"),
            "args": inputs if inputs is not None else input_str,
            "turn": self.turns,
            "started": time.perf_counter(),
            "counters": budget.snapshot(),
        }

    def on_tool_end(self, output, *, run_id: UUID, **kwargs) -> None:
        content = getattr(output, "content", output)
        is_error = getattr(output, "status", None) == "error"
        self._emit_tool_call(run_id, content, is_error)

    def on_tool_error(self, error, *, run_id: UUID, **kwargs) -> None:
        self._emit_tool_call(run_id, f"{type(error).__name__}: {error}", True)

    def _emit_tool_call(self, run_id: UUID, content: Any, is_error: bool) -> None:
        run = self._tool_runs.pop(run_id, None)
        if run is None:
            return
        requests, rate_limited, cache_hits = budget.snapshot()
        tracing.emit(
            "tool_call",
            self.request_id,
            turn=run["turn"],
            tool=run["tool"],
            route=route_of(run["tool"], content),
            args=run["args"],
            is_error=is_error,
            partial=_is_partial(content),
            notion_requests=requests - run["counters"][0],
            notion_rate_limited=rate_limited - run["counters"][1],
            cache_hits=cache_hits - run["counters"][2],
            output_chars=len(content) if isinstance(content, str) else len(str(content)),
            latency_ms=round((time.perf_counter() - run["started"]) * 1000),
        )
