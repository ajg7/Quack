import json
from types import SimpleNamespace

import pytest

from evals import runner, scoring
from quack import config, tracing


def test_normalize_strips_markdown_and_case():
    assert scoring.normalize("**Ten**  rituals\n`today`") == "ten rituals today"


def test_answer_passes_when_every_expected_fragment_is_present():
    score = scoring.score_answer("You have **10** rituals: Pray, Read.", ["10", "pray", "read"])

    assert score.passed is True
    assert not score.missing


def test_answer_reports_missing_fragments():
    score = scoring.score_answer("You have 10 rituals.", ["10", "Pray"])

    assert score.passed is False
    assert score.missing == ["Pray"]


def test_alternatives_accept_any_one_option():
    assert scoring.score_answer("ten items", [["10", "ten"]]).passed is True
    assert scoring.score_answer("some items", [["10", "ten"]]).missing == ["10 | ten"]


def test_forbidden_text_fails_the_answer():
    score = scoring.score_answer("Pray and Legacy item", ["Pray"], ["legacy item"])

    assert score.passed is False
    assert score.forbidden_found == ["legacy item"]


def events_for(request_id="r1", calls=2, requests=4, latency=3000, exhausted=None):
    tool = [
        {"request_id": request_id, "event": "tool_call", "notion_requests": requests // calls}
        for _ in range(calls)
    ]
    end = {
        "request_id": request_id,
        "event": "question_end",
        "turns": 3,
        "notion_requests": requests,
        "notion_rate_limited": 1,
        "cache_hits": 2,
        "input_tokens": 100,
        "output_tokens": 20,
        "latency_ms": latency,
        "budget_exhausted": exhausted,
    }
    return tool + [end]


def test_trace_score_reads_totals_from_question_end():
    trace = scoring.score_trace(events_for())

    assert (trace.tool_calls, trace.notion_requests, trace.rate_limited, trace.cache_hits) == (2, 4, 1, 2)
    assert trace.latency_ms == 3000
    assert trace.within_limits is True


def test_trace_score_flags_each_limit_it_exceeds():
    trace = scoring.score_trace(
        events_for(), {"max_tool_calls": 1, "max_requests": 10, "max_latency_ms": 1000}
    )

    assert trace.violations == ["max_tool_calls: 2 > 1", "max_latency_ms: 3000 > 1000"]


def test_budget_exhaustion_is_a_violation():
    trace = scoring.score_trace(events_for(exhausted="requests"))

    assert trace.within_limits is False


def test_trace_score_without_question_end_sums_tool_events():
    events = [e for e in events_for() if e["event"] == "tool_call"]

    assert scoring.score_trace(events).notion_requests == 4


def test_trace_score_captures_errors():
    trace = scoring.score_trace([{"event": "question_error", "error": "Boom"}])

    assert trace.error == "Boom"


def test_verdict_separates_correctness_from_efficiency():
    ok = scoring.AnswerScore(True)
    bad = scoring.AnswerScore(False, missing=["x"])
    lean = scoring.TraceScore()
    wasteful = scoring.TraceScore(violations=["max_requests: 9 > 5"])

    assert scoring.verdict(ok, lean) == scoring.PASS
    assert scoring.verdict(ok, wasteful) == scoring.PASS_WASTEFUL
    assert scoring.verdict(bad, lean) == scoring.FAIL
    assert scoring.verdict(None, scoring.TraceScore(error="x")) == scoring.ERROR


def summary_row(verdict, calls=1, requests=2, latency=1000):
    return {
        "id": "q",
        "verdict": verdict,
        "trace": {
            "tool_calls": calls,
            "notion_requests": requests,
            "cache_hits": 0,
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": latency,
        },
    }


def test_summary_counts_verdicts_and_totals():
    rows = [summary_row(v) for v in ("pass", "pass-wasteful", "fail", "error")]

    summary = scoring.summarize(rows)

    assert summary["total"] == 4
    assert summary["accuracy"] == 0.5
    assert summary["efficient_accuracy"] == 0.25
    assert summary["notion_requests"] == 8


def test_summary_of_nothing_is_zeroed():
    assert scoring.summarize([])["accuracy"] == 0.0


def write_questions(tmp_path, items):
    path = tmp_path / "q.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def test_load_questions_validates_required_keys(tmp_path):
    path = write_questions(tmp_path, [{"id": "a", "question": "?"}])

    with pytest.raises(runner.EvalSetError, match="must_include"):
        runner.load_questions(path)


def test_load_questions_rejects_duplicate_ids(tmp_path):
    item = {"id": "a", "question": "?", "must_include": ["x"]}

    with pytest.raises(runner.EvalSetError, match="Duplicate"):
        runner.load_questions(write_questions(tmp_path, [item, item]))


def test_load_questions_filters_by_id_and_rejects_unknown(tmp_path):
    items = [
        {"id": "a", "question": "?", "must_include": ["x"]},
        {"id": "b", "question": "?", "must_include": ["y"]},
    ]
    path = write_questions(tmp_path, items)

    assert [q["id"] for q in runner.load_questions(path, {"b"})] == ["b"]
    with pytest.raises(runner.EvalSetError, match="nope"):
        runner.load_questions(path, {"nope"})


def test_shipped_question_file_is_valid():
    assert isinstance(runner.load_questions(), list)


@pytest.fixture
def traces(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path)
    return tmp_path


def fake_run(answer, requests=3):
    def run(question, request_id=None):
        tracing.emit("tool_call", request_id, notion_requests=requests)
        tracing.emit(
            "question_end",
            request_id,
            turns=2,
            notion_requests=requests,
            notion_rate_limited=0,
            cache_hits=0,
            input_tokens=1,
            output_tokens=1,
            latency_ms=500,
            budget_exhausted=None,
        )
        return SimpleNamespace(answer=answer, request_id=request_id)

    return run


def test_run_question_scores_answer_and_trace_separately(traces):
    item = {"id": "a", "question": "?", "must_include": ["ten"], "max_requests": 1}

    row = runner.run_question(item, fake_run("There are ten."))

    assert row["verdict"] == scoring.PASS_WASTEFUL
    assert row["answer_score"]["passed"] is True
    assert row["trace"]["violations"] == ["max_requests: 3 > 1"]


def test_run_question_fails_a_wrong_answer(traces):
    item = {"id": "a", "question": "?", "must_include": ["ten"]}

    assert runner.run_question(item, fake_run("Eleven."))["verdict"] == scoring.FAIL


def test_run_question_reports_crashes_as_errors(traces):
    def crash(question, request_id=None):
        raise RuntimeError("down")

    item = {"id": "a", "question": "?", "must_include": ["x"]}

    row = runner.run_question(item, crash)

    assert row["verdict"] == scoring.ERROR
    assert row["trace"]["error"] == "RuntimeError: down"


def test_write_report_includes_summary_and_rows(tmp_path):
    rows = [summary_row("pass")]

    path = runner.write_report(rows, tmp_path)
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["summary"]["total"] == 1
    assert report["results"] == rows


def test_expected_route_must_appear_in_the_trace():
    events = [{"event": "tool_call", "route": "live"}, {"event": "question_end"}]

    assert scoring.score_trace(events, {"expect_route": "live"}).within_limits is True
    missed = scoring.score_trace(events, {"expect_route": "rag"})
    assert missed.violations == ["route: expected rag, saw live"]
    assert missed.routes == {"live": 1}


def test_pass_rates_average_repeated_runs():
    rows = [
        {"id": "a", "verdict": "pass"},
        {"id": "a", "verdict": "fail"},
        {"id": "b", "verdict": "pass-wasteful"},
    ]

    assert scoring.pass_rates(rows) == {"a": 0.5, "b": 1.0}


def test_run_all_repeats_each_question(traces):
    item = {"id": "a", "question": "?", "must_include": ["ten"]}

    rows = runner.run_all([item], fake_run("ten"), repeat=3)

    assert [row["attempt"] for row in rows] == [1, 2, 3]
