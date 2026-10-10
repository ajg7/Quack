import contextlib
import contextvars
import functools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

from quack import config

STEPS = "steps"
REQUESTS = "requests"
TIME = "time"

_MESSAGES = {
    STEPS: "the tool-call limit ({limit}) was reached",
    REQUESTS: "the Notion request limit ({limit}) was reached",
    TIME: "the time limit ({limit}s) was reached",
}

STOP_INSTRUCTION = (
    "Do not call any more tools. Answer now with what you already have, and say plainly "
    "which parts of the question you could not check."
)


class BudgetExceeded(Exception):
    def __init__(self, kind: str, limit: float) -> None:
        self.kind = kind
        self.limit = limit
        super().__init__(f"Budget exhausted: {_MESSAGES[kind].format(limit=limit)}. {STOP_INSTRUCTION}")


@dataclass
class Budget:
    max_steps: int = field(default_factory=lambda: config.MAX_TOOL_STEPS)
    max_requests: int = field(default_factory=lambda: config.MAX_NOTION_REQUESTS)
    deadline_seconds: float = field(default_factory=lambda: config.REQUEST_DEADLINE_SECONDS)
    steps: int = 0
    requests: int = 0
    rate_limited: int = 0
    cache_hits: int = 0
    exhausted: str | None = None
    started: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _trip(self, kind: str, limit: float) -> BudgetExceeded:
        self.exhausted = self.exhausted or kind
        return BudgetExceeded(kind, limit)

    def expired(self) -> bool:
        return time.monotonic() - self.started > self.deadline_seconds

    def _check_deadline(self) -> None:
        if self.expired():
            raise self._trip(TIME, self.deadline_seconds)

    def must_answer(self) -> bool:
        with self._lock:
            if self.exhausted is None and self.expired():
                self.exhausted = TIME
            return self.exhausted is not None

    def charge_step(self) -> None:
        with self._lock:
            self._check_deadline()
            if self.steps >= self.max_steps:
                raise self._trip(STEPS, self.max_steps)
            self.steps += 1

    def charge_request(self) -> None:
        with self._lock:
            self._check_deadline()
            if self.requests >= self.max_requests:
                raise self._trip(REQUESTS, self.max_requests)
            self.requests += 1

    def note_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited += 1

    def note_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def summary(self) -> dict:
        return {
            "tool_steps": self.steps,
            "notion_requests": self.requests,
            "notion_rate_limited": self.rate_limited,
            "cache_hits": self.cache_hits,
            "budget_exhausted": self.exhausted,
        }


_current: contextvars.ContextVar[Budget | None] = contextvars.ContextVar("quack_budget", default=None)


def current() -> Budget | None:
    return _current.get()


@contextlib.contextmanager
def activate(budget: Budget | None = None) -> Iterator[Budget]:
    budget = budget or Budget()
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def charge_step() -> None:
    budget = _current.get()
    if budget:
        budget.charge_step()


def charge_request() -> None:
    budget = _current.get()
    if budget:
        budget.charge_request()


def note_rate_limited() -> None:
    budget = _current.get()
    if budget:
        budget.note_rate_limited()


def note_cache_hit() -> None:
    budget = _current.get()
    if budget:
        budget.note_cache_hit()


def snapshot() -> tuple[int, int, int]:
    budget = _current.get()
    if budget is None:
        return (0, 0, 0)
    return (budget.requests, budget.rate_limited, budget.cache_hits)


def guarded(handler: Callable[..., dict]) -> Callable[..., dict]:
    @functools.wraps(handler)
    def wrapper(**kwargs):
        charge_step()
        return handler(**kwargs)

    return wrapper
