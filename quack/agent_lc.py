import functools
import os
import time
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import AIMessage
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import StructuredTool, ToolException

from quack import budget, config, tracing
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
    budget: dict = field(default_factory=dict)


RECURSION_LIMIT = 2 * (config.MAX_TOOL_STEPS + config.FINAL_ANSWER_GRACE_TURNS) + 1


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
        func=_report_errors_to_model(budget.guarded(HANDLERS[schema["name"]])),
        name=schema["name"],
        description=schema["description"],
        args_schema=schema["input_schema"],
        handle_tool_error=True,
    )
    for schema in SCHEMAS
]


@wrap_model_call
def answer_when_out_of_budget(request, handler):
    active = budget.current()
    turns = sum(isinstance(message, AIMessage) for message in request.messages)
    max_turns = config.MAX_TOOL_STEPS + config.FINAL_ANSWER_GRACE_TURNS
    if (active and active.must_answer()) or turns >= max_turns:
        request = request.override(tool_choice={"type": "none"})
    return handler(request)


def _build_model(streaming: bool = False) -> ChatAnthropic:
    config.require("ANTHROPIC_API_KEY")
    kwargs = {}
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": workspace_id}
    return ChatAnthropic(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        streaming=streaming,
        timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=config.LLM_MAX_RETRIES,
        **kwargs,
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
        middleware=[answer_when_out_of_budget],
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

    with budget.activate() as run_budget:
        try:
            out = agent.invoke(
                {"messages": messages},
                config={
                    "callbacks": [trace_handler, *extra_handlers],
                    "recursion_limit": RECURSION_LIMIT,
                },
            )
        except Exception as e:
            tracing.emit(
                "question_error",
                request_id,
                error=f"{type(e).__name__}: {e}",
                turns=trace_handler.turns,
                latency_ms=round((time.perf_counter() - started) * 1000),
                **run_budget.summary(),
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
        **run_budget.summary(),
    )

    return RunResult(
        answer=answer,
        request_id=request_id,
        turns=trace_handler.turns,
        tool_calls=trace_handler.tool_calls,
        input_tokens=trace_handler.input_tokens,
        output_tokens=trace_handler.output_tokens,
        latency_ms=latency_ms,
        budget=run_budget.summary(),
    )


def ask(question: str) -> str:
    return run(question).answer
