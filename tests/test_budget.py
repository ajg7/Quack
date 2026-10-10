import threading

import pytest

from quack import budget
from quack.budget import Budget, BudgetExceeded


def test_steps_are_capped():
    b = Budget(max_steps=2)
    b.charge_step()
    b.charge_step()

    with pytest.raises(BudgetExceeded) as caught:
        b.charge_step()

    assert caught.value.kind == budget.STEPS
    assert b.exhausted == budget.STEPS
    assert b.steps == 2


def test_requests_are_capped():
    b = Budget(max_requests=1)
    b.charge_request()

    with pytest.raises(BudgetExceeded) as caught:
        b.charge_request()

    assert caught.value.kind == budget.REQUESTS


def test_deadline_trips_both_charges():
    b = Budget(deadline_seconds=-1)

    with pytest.raises(BudgetExceeded) as step:
        b.charge_step()
    with pytest.raises(BudgetExceeded) as request:
        b.charge_request()

    assert step.value.kind == budget.TIME
    assert request.value.kind == budget.TIME
    assert b.exhausted == budget.TIME


def test_first_exhaustion_reason_is_kept():
    b = Budget(max_steps=0, max_requests=0)

    with pytest.raises(BudgetExceeded):
        b.charge_step()
    with pytest.raises(BudgetExceeded):
        b.charge_request()

    assert b.exhausted == budget.STEPS


def test_error_message_tells_the_model_to_stop():
    with pytest.raises(BudgetExceeded, match="Do not call any more tools"):
        Budget(max_steps=0).charge_step()


def test_charges_are_noops_without_an_active_budget():
    budget.charge_step()
    budget.charge_request()
    budget.note_cache_hit()
    budget.note_rate_limited()

    assert budget.current() is None
    assert budget.snapshot() == (0, 0, 0)


def test_activate_scopes_the_budget_and_restores_the_previous_one():
    with budget.activate(Budget()) as outer:
        with budget.activate(Budget()) as inner:
            assert budget.current() is inner
        assert budget.current() is outer

    assert budget.current() is None


def test_snapshot_reports_requests_rate_limits_and_cache_hits():
    with budget.activate(Budget()):
        budget.charge_request()
        budget.charge_request()
        budget.note_rate_limited()
        budget.note_cache_hit()

        assert budget.snapshot() == (2, 1, 1)


def test_summary_names_every_counter():
    b = Budget()
    b.charge_step()
    b.charge_request()

    assert b.summary() == {
        "tool_steps": 1,
        "notion_requests": 1,
        "notion_rate_limited": 0,
        "cache_hits": 0,
        "budget_exhausted": None,
    }


def test_guarded_charges_a_step_before_running_the_handler():
    calls = []

    def handler(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    with budget.activate(Budget(max_steps=1)):
        guarded = budget.guarded(handler)
        assert guarded(query="a") == {"ok": True}

        with pytest.raises(BudgetExceeded):
            guarded(query="b")

    assert calls == [{"query": "a"}]


def test_concurrent_charges_never_exceed_the_cap():
    b = Budget(max_requests=50)
    granted = []

    def worker():
        for _ in range(20):
            try:
                b.charge_request()
                granted.append(1)
            except BudgetExceeded:
                pass

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 50
    assert b.requests == 50
