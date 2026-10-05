import functools
import os
import time
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import StructuredTool, ToolException

from quack import config, tracing
from quack.prompt import load_system_prompt
from quack.tools import HANDLERS, SCHEMAS
from quack.tracing_lc import TraceHandler


@dataclass
class RunResult:
    answer: str
    request_id: str
    turns: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


def _report_errors_to_model(func):
    @functools.wraps(func)
    def wrapper(**kwargs):
        try:
            return func(**kwargs)
        except Exception as e:
            raise ToolException(f"{type(e).__name__}: {e}") from e

    return wrapper


tools = [
    StructuredTool.from_function(
        func=_report_errors_to_model(HANDLERS[schema["name"]]),
        name=schema["name"],
        description=schema["description"],
        args_schema=schema["input_schema"],
        handle_tool_error=True,
    )
    for schema in SCHEMAS
]


def _build_model(streaming: bool = False) -> ChatAnthropic:
    config.require("ANTHROPIC_API_KEY")
    kwargs = {}
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": workspace_id}
    return ChatAnthropic(
        model=config.MODEL, max_tokens=config.MAX_TOKENS, streaming=streaming, **kwargs
    )


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def run(
    question: str,
    history: list[dict] | None = None,
    handlers: list | None = None,
    request_id: str | None = None,
) -> RunResult:
    request_id = request_id or tracing.new_request_id()
    started = time.perf_counter()
    extra_handlers = list(handlers or [])

    agent = create_agent(
        _build_model(streaming=bool(extra_handlers)),
        tools,
        system_prompt=load_system_prompt(),
    )
    trace_handler = TraceHandler(request_id)

    tracing.emit(
        "question_start",
        request_id,
        question=question,
        model=config.MODEL,
        framework="langchain",
        history_messages=len(history or []),
    )

    messages = list(history or []) + [{"role": "user", "content": question}]

    try:
        out = agent.invoke(
            {"messages": messages},
            config={"callbacks": [trace_handler, *extra_handlers]},
        )
    except Exception as e:
        tracing.emit(
            "question_error",
            request_id,
            error=f"{type(e).__name__}: {e}",
            turns=trace_handler.turns,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        raise

    answer = _extract_text(out["messages"][-1].content)
    latency_ms = round((time.perf_counter() - started) * 1000)

    tracing.emit(
        "question_end",
        request_id,
        turns=trace_handler.turns,
        tool_calls=trace_handler.tool_calls,
        input_tokens=trace_handler.input_tokens,
        output_tokens=trace_handler.output_tokens,
        latency_ms=latency_ms,
        answer_chars=len(answer),
    )

    return RunResult(
        answer=answer,
        request_id=request_id,
        turns=trace_handler.turns,
        tool_calls=trace_handler.tool_calls,
        input_tokens=trace_handler.input_tokens,
        output_tokens=trace_handler.output_tokens,
        latency_ms=latency_ms,
    )


def ask(question: str) -> str:
    return run(question).answer
