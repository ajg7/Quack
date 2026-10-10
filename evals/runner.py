import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from quack import agent_lc, config, tracing
from quack.integrations import notion

from evals import scoring

QUESTIONS_PATH = config.EVAL_DIR / "questions.json"
REQUIRED_KEYS = ("id", "question", "must_include")
LIMIT_KEYS = ("max_tool_calls", "max_requests", "max_latency_ms", "expect_route")


class EvalSetError(ValueError):
    pass


def load_questions(path: Path = QUESTIONS_PATH, ids: set[str] | None = None) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        questions = json.load(f)

    seen = set()
    for item in questions:
        missing = [key for key in REQUIRED_KEYS if key not in item]
        if missing:
            raise EvalSetError(f"Question {item.get('id', '?')} is missing {', '.join(missing)}")
        if item["id"] in seen:
            raise EvalSetError(f"Duplicate question id {item['id']}")
        seen.add(item["id"])

    if ids:
        unknown = ids - seen
        if unknown:
            raise EvalSetError(f"Unknown question ids: {', '.join(sorted(unknown))}")
        questions = [item for item in questions if item["id"] in ids]
    return questions


def run_question(item: dict, run=agent_lc.run) -> dict:
    notion.clear_cache()
    started = time.perf_counter()
    request_id = tracing.new_request_id()
    answer_text = ""
    failure = None

    try:
        answer_text = run(item["question"], request_id=request_id).answer
    except Exception as e:
        failure = f"{type(e).__name__}: {e}"

    events = tracing.read_events(request_id)
    limits = {key: item[key] for key in LIMIT_KEYS if key in item}
    trace = scoring.score_trace(events, limits)
    if failure and not trace.error:
        trace.error = failure

    answer = None
    if not failure:
        answer = scoring.score_answer(answer_text, item["must_include"], item.get("must_exclude"))

    return {
        "id": item["id"],
        "question": item["question"],
        "request_id": request_id,
        "verdict": scoring.verdict(answer, trace),
        "answer": answer_text,
        "answer_score": asdict(answer) if answer else None,
        "trace": {**asdict(trace), "violations": trace.violations},
        "wall_ms": round((time.perf_counter() - started) * 1000),
    }


def run_all(questions: list[dict], run=agent_lc.run, on_result=None, repeat: int = 1) -> list[dict]:
    rows = []
    for item in questions:
        for attempt in range(1, repeat + 1):
            row = {**run_question(item, run), "attempt": attempt}
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def format_row(row: dict) -> str:
    trace = row["trace"]
    latency = f"{trace['latency_ms'] / 1000:.1f}s" if trace["latency_ms"] is not None else "-"
    routes = ",".join(f"{name}x{count}" for name, count in sorted(trace["routes"].items())) or "-"
    return (
        f"{row['id']:<24} {row['verdict']:<14} calls={trace['tool_calls']:<3} "
        f"req={trace['notion_requests']:<3} cache={trace['cache_hits']:<3} {latency:<7} {routes}"
    )


def write_report(rows: list[dict], directory: Path | None = None) -> Path:
    directory = directory or config.TRACE_DIR / "evals"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"eval-{stamp}.json"
    report = {"model": config.MODEL, "summary": scoring.summarize(rows), "results": rows}
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
