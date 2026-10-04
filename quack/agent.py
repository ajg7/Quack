from quack import config, tools, tracing
from quack.integrations import notion
from pathlib import Path
import json
import time

def ask(question: str) -> str:
  client = config.anthropic_client()
  request_id = tracing.new_request_id()
  started = time.perf_counter()

  system_prompt_path = Path(__file__).parent / "prompts" / "system.md"

  with open(system_prompt_path, encoding="utf-8") as f:
    system_prompt = f.read()

  messages = [
    {"role": "user", "content": question},
  ]

  tracing.emit("question_start", request_id, question=question, model=config.MODEL)

  turns = 0
  tool_calls = 0
  input_tokens = 0
  output_tokens = 0

  try:
    while True:
      turn_started = time.perf_counter()
      response = client.messages.create(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        system=system_prompt,
        tools=tools.SCHEMAS,
        messages=messages,
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
        )
        return answer

      tool_results = []
      for block in response.content:
        if block.type != "tool_use":
          continue
        tool_calls += 1
        tool_started = time.perf_counter()
        requests_before = notion.stats.requests
        rate_limited_before = notion.stats.rate_limited
        is_error = False
        try:
          result = tools.HANDLERS[block.name](**block.input)
          content = json.dumps(result)
        except Exception as e:
          is_error = True
          content = f"{type(e).__name__}: {e}"

        tracing.emit(
          "tool_call",
          request_id,
          turn=turns,
          tool=block.name,
          args=block.input,
          is_error=is_error,
          partial=bool(result.get("partial")) if not is_error and isinstance(result, dict) else False,
          notion_requests=notion.stats.requests - requests_before,
          notion_rate_limited=notion.stats.rate_limited - rate_limited_before,
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
        tool_results.append(tool_result)

      messages.append({"role": "user", "content": tool_results})
  except Exception as e:
    tracing.emit(
      "question_error",
      request_id,
      error=f"{type(e).__name__}: {e}",
      turns=turns,
      latency_ms=round((time.perf_counter() - started) * 1000),
    )
    raise
