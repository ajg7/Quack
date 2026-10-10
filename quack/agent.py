from quack import budget, config, router, tools, tracing
from concurrent.futures import ThreadPoolExecutor
from quack.prompt import load_system_prompt
import contextvars
import json
import time

def _run_tool(block, request_id: str, turn: int) -> dict:
  tool_started = time.perf_counter()
  requests_before, rate_limited_before, hits_before = budget.snapshot()
  is_error = False
  result = None
  try:
    result = budget.guarded(tools.HANDLERS[block.name])(**block.input)
    content = json.dumps(result)
  except Exception as e:
    is_error = True
    content = f"{type(e).__name__}: {e}"

  requests_after, rate_limited_after, hits_after = budget.snapshot()
  tracing.emit(
    "tool_call",
    request_id,
    turn=turn,
    tool=block.name,
    route=router.route_for(block.name, result),
    args=block.input,
    is_error=is_error,
    partial=bool(result.get("partial")) if isinstance(result, dict) else False,
    notion_requests=requests_after - requests_before,
    notion_rate_limited=rate_limited_after - rate_limited_before,
    cache_hits=hits_after - hits_before,
    output_chars=len(content),
    latency_ms=round((time.perf_counter() - tool_started) * 1000),
  )

  tool_result = {
    "type": "tool_result",
    "tool_use_id": block.id,
    "content": content,
  }
  if is_error:
    tool_result["is_error"] = True
  return tool_result

def _run_tools(blocks: list, request_id: str, turn: int) -> list[dict]:
  if len(blocks) == 1:
    return [_run_tool(blocks[0], request_id, turn)]
  with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
    futures = [
      pool.submit(contextvars.copy_context().run, _run_tool, block, request_id, turn)
      for block in blocks
    ]
    return [future.result() for future in futures]

def ask(question: str) -> str:
  client = config.anthropic_client()
  request_id = tracing.new_request_id()
  started = time.perf_counter()

  system_prompt = load_system_prompt()

  messages = [
    {"role": "user", "content": question},
  ]

  tracing.emit("question_start", request_id, question=question, model=config.MODEL)

  turns = 0
  tool_calls = 0
  input_tokens = 0
  output_tokens = 0
  max_turns = config.MAX_TOOL_STEPS + config.FINAL_ANSWER_GRACE_TURNS

  with budget.activate() as run_budget:
    try:
      while True:
        turn_started = time.perf_counter()
        must_answer = run_budget.must_answer() or turns >= max_turns
        extra = {"tool_choice": {"type": "none"}} if must_answer else {}
        response = client.messages.create(
          model=config.MODEL,
          max_tokens=config.MAX_TOKENS,
          system=system_prompt,
          tools=tools.SCHEMAS,
          messages=messages,
          **extra,
        )
        turns += 1
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        tracing.emit(
          "claude_turn",
          request_id,
          turn=turns,
          stop_reason=response.stop_reason,
          input_tokens=response.usage.input_tokens,
          output_tokens=response.usage.output_tokens,
          latency_ms=round((time.perf_counter() - turn_started) * 1000),
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
          answer = "".join(block.text for block in response.content if block.type == "text")
          tracing.emit(
            "question_end",
            request_id,
            turns=turns,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
            answer_chars=len(answer),
            **run_budget.summary(),
          )
          return answer

        tool_blocks = [block for block in response.content if block.type == "tool_use"]
        tool_calls += len(tool_blocks)
        messages.append({"role": "user", "content": _run_tools(tool_blocks, request_id, turns)})
    except Exception as e:
      tracing.emit(
        "question_error",
        request_id,
        error=f"{type(e).__name__}: {e}",
        turns=turns,
        latency_ms=round((time.perf_counter() - started) * 1000),
        **run_budget.summary(),
      )
      raise
