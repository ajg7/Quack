import json

import pytest

from quack import budget, config
from quack.integrations import notion


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class NoLimiter:
    def acquire(self):
        pass


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    monkeypatch.setattr(notion, "_limiter", NoLimiter())
    monkeypatch.setattr(config, "notion_headers", lambda: {})
    monkeypatch.setattr(notion.time, "sleep", lambda s: None)
    notion.clear_cache()
    yield
    notion.clear_cache()


def script(monkeypatch, responses):
    queue = list(responses)
    sent = []

    def fake(method, url, **kwargs):
        sent.append((method, url))
        return queue.pop(0)

    monkeypatch.setattr(notion.requests, "request", fake)
    return sent


def test_repeated_identical_request_is_served_from_cache(monkeypatch):
    sent = script(monkeypatch, [FakeResponse(200, {"n": 1})])

    with budget.activate() as b:
        first = notion._request("GET", "/pages/a")
        second = notion._request("GET", "/pages/a")

    assert first == second == {"n": 1}
    assert len(sent) == 1
    assert b.requests == 1
    assert b.cache_hits == 1


def test_different_payloads_are_cached_separately(monkeypatch):
    sent = script(monkeypatch, [FakeResponse(200, {"n": 1}), FakeResponse(200, {"n": 2})])

    first = notion._request("POST", "/search", json={"query": "a"})
    second = notion._request("POST", "/search", json={"query": "b"})

    assert (first, second) == ({"n": 1}, {"n": 2})
    assert len(sent) == 2


def test_errors_are_not_cached(monkeypatch):
    script(monkeypatch, [FakeResponse(400, {"message": "bad"}), FakeResponse(200, {"n": 1})])

    with pytest.raises(Exception):
        notion._request("GET", "/x")

    assert notion._request("GET", "/x") == {"n": 1}


def test_request_budget_blocks_the_http_call(monkeypatch):
    sent = script(monkeypatch, [FakeResponse(200, {"n": 1})] * 5)

    with budget.activate(budget.Budget(max_requests=2)):
        notion._request("GET", "/a")
        notion._request("GET", "/b")
        with pytest.raises(budget.BudgetExceeded):
            notion._request("GET", "/c")

    assert len(sent) == 2


def test_retries_spend_request_budget(monkeypatch):
    script(monkeypatch, [FakeResponse(429)] * 4)

    with budget.activate(budget.Budget(max_requests=2)) as b:
        with pytest.raises(budget.BudgetExceeded):
            notion._request("GET", "/x")

    assert b.requests == 2
    assert b.rate_limited == 2


def test_paginate_returns_partial_with_budget_reason(monkeypatch):
    pages = [
        FakeResponse(200, {"results": [1, 2], "has_more": True, "next_cursor": "c"}),
        FakeResponse(200, {"results": [3], "has_more": False}),
    ]
    script(monkeypatch, pages)

    with budget.activate(budget.Budget(max_requests=1)):
        out = notion._paginate("POST", "/search", {"query": "q"})

    assert out.results == [1, 2]
    assert out.partial is True
    assert out.has_more is True
    assert out.reason == notion.BUDGET


def test_retry_after_is_capped(monkeypatch):
    waits = []
    monkeypatch.setattr(notion.time, "sleep", waits.append)
    script(monkeypatch, [FakeResponse(429, headers={"Retry-After": "3600"}), FakeResponse(200, {"n": 1})])

    notion._request("GET", "/x")

    assert waits == [config.NOTION_MAX_RETRY_AFTER]


def test_search_forwards_limit_to_page_size(monkeypatch):
    bodies = []

    def fake(method, url, **kwargs):
        bodies.append(kwargs["json"])
        return FakeResponse(200, {"results": [1, 2, 3], "has_more": True, "next_cursor": "c"})

    monkeypatch.setattr(notion.requests, "request", fake)

    out = notion.search("agoge", limit=2)

    assert bodies[0]["page_size"] == 2
    assert out.results == [1, 2]
    assert out.has_more is True
