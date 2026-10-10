import queue
import threading
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler

from quack import agent_lc, config, tracing
from quack.tracing_lc import route_of


class StreamCancelled(Exception):
    pass


_DONE = object()


def describe_tool_call(tool: str, args: dict | None) -> str:
    args = args or {}
    if tool == "search_notion":
        return f"Searching Notion for \"{args.get('query', '')}\""
    if tool == "query_database":
        flt = args.get("filter")
        return "Querying a database" + (" with a filter" if flt else "")
    if tool == "aggregate_database":
        return "Counting rows in a database"
    if tool == "get_page":
        return "Reading a page"
    if tool == "semantic_search":
        return f"Searching by meaning for \"{args.get('query', '')}\""
    return f"Running {tool}"


def _chunk_text(chunk: Any) -> str:
    content = getattr(getattr(chunk, "message", None), "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


class StreamHandler(BaseCallbackHandler):
    raise_error = True

    def __init__(self, events: "queue.Queue", cancelled: threading.Event) -> None:
        self._events = events
        self._cancelled = cancelled
        self._tools: dict[Any, dict] = {}
        self.steps = 0

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise StreamCancelled()

    def on_llm_new_token(self, token, *, chunk=None, **kwargs) -> None:
        self._check_cancelled()
        text = _chunk_text(chunk)
        if text:
            self._events.put({"event": "token", "data": {"text": text}})

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs) -> None:
        self._check_cancelled()
        self.steps += 1
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        args = inputs if isinstance(inputs, dict) else {}
        self._tools[run_id] = {"tool": name, "step": self.steps}
        self._events.put(
            {
                "event": "progress",
                "data": {
                    "status": "start",
                    "step": self.steps,
                    "tool": name,
                    "message": describe_tool_call(name, args),
                    "args": args,
                },
            }
        )

    def _finish_tool(self, run_id, ok: bool, content=None) -> None:
        info = self._tools.pop(run_id, None)
        if info is None:
            return
        self._events.put(
            {
                "event": "progress",
                "data": {
                    "status": "done" if ok else "error",
                    "step": info["step"],
                    "tool": info["tool"],
                    "route": route_of(info["tool"], content),
                    "message": f"{info['tool']} finished" if ok else f"{info['tool']} failed",
                },
            }
        )

    def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        self._finish_tool(
            run_id, getattr(output, "status", None) != "error", getattr(output, "content", output)
        )

    def on_tool_error(self, error, *, run_id, **kwargs) -> None:
        self._finish_tool(run_id, False)


def _public_error_message(request_id: str) -> str:
    return f"Quack hit an internal error and could not finish this answer. Reference: {request_id}."


def stream_events(
    question: str, history: list[dict] | None = None, model: str | None = None
) -> Iterator[dict]:
    events: "queue.Queue" = queue.Queue()
    cancelled = threading.Event()
    request_id = tracing.new_request_id()
    handler = StreamHandler(events, cancelled)

    def worker() -> None:
        try:
            result = agent_lc.run(question, history, [handler], request_id, model)
            events.put(
                {
                    "event": "done",
                    "data": {
                        "answer": result.answer,
                        "request_id": result.request_id,
                        "turns": result.turns,
                        "tool_calls": result.tool_calls,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "latency_ms": result.latency_ms,
                        "budget_exhausted": getattr(result, "budget", {}).get("budget_exhausted"),
                    },
                }
            )
        except StreamCancelled:
            pass
        except Exception as e:
            tracing.emit("stream_error", request_id, error=f"{type(e).__name__}: {e}"[:2000])
            events.put(
                {
                    "event": "error",
                    "data": {"message": _public_error_message(request_id), "request_id": request_id},
                }
            )
        finally:
            events.put(_DONE)

    threading.Thread(target=worker, daemon=True).start()

    yield {"event": "start", "data": {"request_id": request_id}}

    try:
        while True:
            try:
                item = events.get(timeout=config.SSE_KEEPALIVE_SECONDS)
            except queue.Empty:
                yield {"event": "ping", "data": {}}
                continue
            if item is _DONE:
                break
            yield item
    finally:
        cancelled.set()
