import re
from dataclasses import dataclass, field

PASS = "pass"
PASS_WASTEFUL = "pass-wasteful"
FAIL = "fail"
ERROR = "error"


def normalize(text: str) -> str:
    stripped = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _alternatives(expected: str | list[str]) -> list[str]:
    return [expected] if isinstance(expected, str) else list(expected)


@dataclass
class AnswerScore:
    passed: bool
    missing: list[str] = field(default_factory=list)
    forbidden_found: list[str] = field(default_factory=list)


def score_answer(
    answer: str,
    must_include: list[str | list[str]] | None = None,
    must_exclude: list[str] | None = None,
) -> AnswerScore:
    haystack = normalize(answer)

    missing = []
    for expected in must_include or []:
        options = _alternatives(expected)
        if not any(normalize(option) in haystack for option in options):
            missing.append(" | ".join(options))

    forbidden_found = [text for text in must_exclude or [] if normalize(text) in haystack]

    return AnswerScore(not missing and not forbidden_found, missing, forbidden_found)


@dataclass
class TraceScore:
    turns: int = 0
    tool_calls: int = 0
    notion_requests: int = 0
    rate_limited: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int | None = None
    budget_exhausted: str | None = None
    routes: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    violations: list[str] = field(default_factory=list)

    @property
    def within_limits(self) -> bool:
        return not self.violations


def score_trace(events: list[dict], limits: dict | None = None) -> TraceScore:
    limits = limits or {}
    score = TraceScore()

    tool_events = [e for e in events if e.get("event") == "tool_call"]
    end = next((e for e in reversed(events) if e.get("event") == "question_end"), None)
    failure = next((e for e in reversed(events) if e.get("event") == "question_error"), None)

    score.tool_calls = len(tool_events)
    for event in tool_events:
        route = event.get("route")
        if route:
            score.routes[route] = score.routes.get(route, 0) + 1
    if end:
        score.turns = end.get("turns", 0)
        score.notion_requests = end.get("notion_requests", 0)
        score.rate_limited = end.get("notion_rate_limited", 0)
        score.cache_hits = end.get("cache_hits", 0)
        score.input_tokens = end.get("input_tokens", 0)
        score.output_tokens = end.get("output_tokens", 0)
        score.latency_ms = end.get("latency_ms")
        score.budget_exhausted = end.get("budget_exhausted")
    else:
        score.notion_requests = sum(e.get("notion_requests", 0) for e in tool_events)
        score.rate_limited = sum(e.get("notion_rate_limited", 0) for e in tool_events)
        score.cache_hits = sum(e.get("cache_hits", 0) for e in tool_events)
    if failure:
        score.error = failure.get("error")

    checks = (
        ("max_tool_calls", score.tool_calls),
        ("max_requests", score.notion_requests),
        ("max_latency_ms", score.latency_ms),
    )
    for key, actual in checks:
        limit = limits.get(key)
        if limit is not None and actual is not None and actual > limit:
            score.violations.append(f"{key}: {actual} > {limit}")
    expected_route = limits.get("expect_route")
    if expected_route and expected_route not in score.routes:
        seen = ", ".join(sorted(score.routes)) or "none"
        score.violations.append(f"route: expected {expected_route}, saw {seen}")
    if score.budget_exhausted:
        score.violations.append(f"budget exhausted: {score.budget_exhausted}")

    return score


def verdict(answer: AnswerScore | None, trace: TraceScore) -> str:
    if trace.error or answer is None:
        return ERROR
    if not answer.passed:
        return FAIL
    return PASS if trace.within_limits else PASS_WASTEFUL


def pass_rates(rows: list[dict]) -> dict[str, float]:
    by_id: dict[str, list[bool]] = {}
    for row in rows:
        by_id.setdefault(row["id"], []).append(row["verdict"] in (PASS, PASS_WASTEFUL))
    return {question_id: round(sum(results) / len(results), 3) for question_id, results in by_id.items()}


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    counts = {name: sum(1 for r in rows if r["verdict"] == name) for name in (PASS, PASS_WASTEFUL, FAIL, ERROR)}
    answered = [r for r in rows if r["verdict"] != ERROR]
    latencies = sorted(r["trace"]["latency_ms"] for r in answered if r["trace"]["latency_ms"] is not None)
    return {
        "total": total,
        **counts,
        "accuracy": round((counts[PASS] + counts[PASS_WASTEFUL]) / total, 3) if total else 0.0,
        "efficient_accuracy": round(counts[PASS] / total, 3) if total else 0.0,
        "tool_calls": sum(r["trace"]["tool_calls"] for r in rows),
        "notion_requests": sum(r["trace"]["notion_requests"] for r in rows),
        "cache_hits": sum(r["trace"]["cache_hits"] for r in rows),
        "input_tokens": sum(r["trace"]["input_tokens"] for r in rows),
        "output_tokens": sum(r["trace"]["output_tokens"] for r in rows),
        "pass_rates": pass_rates(rows),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
    }
