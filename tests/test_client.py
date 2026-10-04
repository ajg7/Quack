import json
import time

import pytest
import requests

from quack import config, tracing
from quack.integrations import notion
from quack.integrations.notion import NotionRateLimitError, NotionResults, RateLimiter


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
def fresh_stats_and_no_limiter(monkeypatch):
    monkeypatch.setattr(notion, "_limiter", NoLimiter())
    monkeypatch.setattr(notion, "stats", notion.NotionStats())
    monkeypatch.setattr(config, "notion_headers", lambda: {})


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(notion.time, "sleep", lambda s: recorded.append(s))
    return recorded


def script_responses(monkeypatch, responses):
    queue = list(responses)
    monkeypatch.setattr(notion.requests, "request", lambda *a, **k: queue.pop(0))
    return queue


def test_rate_limiter_spaces_requests():
    limiter = RateLimiter(20)
    started = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - started

    assert elapsed >= 3 * 0.05 - 0.01


def test_rate_limiter_first_acquire_does_not_wait():
    limiter = RateLimiter(1)
    started = time.monotonic()
    limiter.acquire()

    assert time.monotonic() - started < 0.1


def test_retry_after_reads_header():
    assert notion._retry_after(FakeResponse(429, headers={"Retry-After": "2.5"})) == 2.5


def test_retry_after_defaults_when_missing_or_garbage():
    assert notion._retry_after(FakeResponse(429)) == config.NOTION_DEFAULT_RETRY_AFTER
    bad = FakeResponse(429, headers={"Retry-After": "soon"})
    assert notion._retry_after(bad) == config.NOTION_DEFAULT_RETRY_AFTER


def test_request_returns_json_on_200(monkeypatch, sleeps):
    script_responses(monkeypatch, [FakeResponse(200, {"ok": True})])

    assert notion._request("GET", "/x") == {"ok": True}
    assert notion.stats.requests == 1
    assert notion.stats.rate_limited == 0


def test_request_retries_after_429_and_honors_retry_after(monkeypatch, sleeps):
    script_responses(
        monkeypatch,
        [FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200, {"ok": True})],
    )

    assert notion._request("GET", "/x") == {"ok": True}
    assert sleeps == [2.0]
    assert notion.stats.requests == 2
    assert notion.stats.rate_limited == 1


def test_request_raises_after_exhausting_retries(monkeypatch, sleeps):
    attempts = config.NOTION_MAX_RETRIES + 1
    script_responses(monkeypatch, [FakeResponse(429)] * attempts)

    with pytest.raises(NotionRateLimitError):
        notion._request("GET", "/x")

    assert notion.stats.requests == attempts
    assert notion.stats.rate_limited == attempts


def test_request_does_not_sleep_after_final_attempt(monkeypatch, sleeps):
    script_responses(monkeypatch, [FakeResponse(429)] * (config.NOTION_MAX_RETRIES + 1))

    with pytest.raises(NotionRateLimitError):
        notion._request("GET", "/x")

    assert len(sleeps) == config.NOTION_MAX_RETRIES


def test_request_raises_http_error_with_body_on_other_status(monkeypatch, sleeps):
    script_responses(monkeypatch, [FakeResponse(400, {"message": "bad filter"})])

    with pytest.raises(requests.exceptions.HTTPError, match="bad filter"):
        notion._request("POST", "/x")

    assert notion.stats.requests == 1


def test_paginate_follows_cursor_until_exhausted(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"results": [1, 2], "has_more": True, "next_cursor": "c1"}
        return {"results": [3], "has_more": False, "next_cursor": None}

    monkeypatch.setattr(notion, "_request", fake_request)

    out = notion._paginate("POST", "/search", {"query": "q"})

    assert out == NotionResults([1, 2, 3], partial=False)
    assert calls[0]["json"] == {"query": "q"}
    assert calls[1]["json"] == {"query": "q", "start_cursor": "c1"}


def test_paginate_uses_params_for_get(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(kwargs)
        return {"results": [], "has_more": False}

    monkeypatch.setattr(notion, "_request", fake_request)

    notion._paginate("GET", "/blocks/x/children")

    assert "params" in calls[0] and "json" not in calls[0]


def test_paginate_returns_partial_when_retries_exhausted_midway(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"results": [1, 2], "has_more": True, "next_cursor": "c1"}
        raise NotionRateLimitError("gave up")

    monkeypatch.setattr(notion, "_request", fake_request)

    out = notion._paginate("POST", "/search", {"query": "q"})

    assert out.results == [1, 2]
    assert out.partial is True


def test_paginate_partial_and_empty_when_first_request_fails(monkeypatch):
    def fake_request(method, path, **kwargs):
        raise NotionRateLimitError("gave up")

    monkeypatch.setattr(notion, "_request", fake_request)

    out = notion._paginate("POST", "/search", {})

    assert out == NotionResults([], partial=True)


def test_trace_emit_writes_one_json_line(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path)

    tracing.emit("tool_call", "abc123", tool="search_notion", latency_ms=12)
    tracing.emit("claude_turn", "abc123", turn=1)

    lines = (tmp_path / tracing.TRACE_FILE).read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]

    assert [e["event"] for e in events] == ["tool_call", "claude_turn"]
    assert {e["request_id"] for e in events} == {"abc123"}
    assert events[0]["tool"] == "search_notion"
    assert "ts" in events[0]


def test_trace_emit_never_raises(monkeypatch):
    class Boom:
        def mkdir(self, *a, **k):
            raise OSError("disk full")

    monkeypatch.setattr(config, "TRACE_DIR", Boom())

    tracing.emit("tool_call", "abc123")


def test_new_request_ids_are_unique():
    assert len({tracing.new_request_id() for _ in range(50)}) == 50
