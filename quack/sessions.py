import threading

from quack import config


class SessionStore:
    def __init__(self, max_messages: int = config.CHAT_HISTORY_MAX_MESSAGES) -> None:
        self._max_messages = max_messages
        self._sessions: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            return [dict(message) for message in self._sessions.get(session_id, [])]

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
        with self._lock:
            messages = self._sessions.setdefault(session_id, [])
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
            overflow = len(messages) - self._max_messages
            if overflow > 0:
                overflow += overflow % 2
                del messages[:overflow]

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
