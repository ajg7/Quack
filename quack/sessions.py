import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from quack import config


@dataclass
class _Session:
    touched: float
    messages: list[dict] = field(default_factory=list)


class SessionStore:
    def __init__(
        self,
        max_messages: int = config.CHAT_HISTORY_MAX_MESSAGES,
        max_sessions: int = config.SESSION_MAX_COUNT,
        ttl_seconds: float = config.SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_messages = max_messages
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._in_flight: dict[str, float] = {}
        self._lock = threading.Lock()

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._ttl_seconds
        while self._sessions:
            oldest = next(iter(self._sessions.values()))
            if oldest.touched > cutoff:
                break
            self._sessions.popitem(last=False)

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            now = self._clock()
            self._evict_expired(now)
            session = self._sessions.get(session_id)
            if session is None:
                return []
            session.touched = now
            self._sessions.move_to_end(session_id)
            return [dict(message) for message in session.messages]

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
        with self._lock:
            now = self._clock()
            self._evict_expired(now)
            session = self._sessions.setdefault(session_id, _Session(touched=now))
            session.touched = now
            self._sessions.move_to_end(session_id)
            messages = session.messages
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
            overflow = len(messages) - self._max_messages
            if overflow > 0:
                overflow += overflow % 2
                del messages[:overflow]
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def try_begin_turn(self, session_id: str) -> bool:
        with self._lock:
            now = self._clock()
            started = self._in_flight.get(session_id)
            if started is not None and now - started < config.TURN_LOCK_SECONDS:
                return False
            self._in_flight[session_id] = now
            return True

    def end_turn(self, session_id: str) -> None:
        with self._lock:
            self._in_flight.pop(session_id, None)

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
