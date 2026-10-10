from quack import config
from quack.sessions import SessionStore


def test_unknown_session_has_empty_history():
    assert SessionStore().get("nope") == []


def test_turns_are_stored_in_order():
    store = SessionStore()

    store.append_turn("s", "q1", "a1")
    store.append_turn("s", "q2", "a2")

    assert store.get("s") == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_sessions_are_isolated():
    store = SessionStore()

    store.append_turn("a", "q", "r")

    assert store.get("b") == []


def test_get_returns_a_copy():
    store = SessionStore()
    store.append_turn("s", "q", "r")

    store.get("s")[0]["content"] = "mutated"
    store.get("s").clear()

    assert store.get("s")[0]["content"] == "q"


def test_history_is_trimmed_in_whole_turns():
    store = SessionStore(max_messages=4)

    for i in range(5):
        store.append_turn("s", f"q{i}", f"a{i}")

    history = store.get("s")
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "q3"}
    assert history[-1] == {"role": "assistant", "content": "a4"}


def test_odd_cap_never_starts_history_with_an_assistant_message():
    store = SessionStore(max_messages=5)

    for i in range(4):
        store.append_turn("s", f"q{i}", f"a{i}")

    assert store.get("s")[0]["role"] == "user"


def test_clear_reports_whether_anything_was_removed():
    store = SessionStore()
    store.append_turn("s", "q", "r")

    assert store.clear("s") is True
    assert store.clear("s") is False
    assert store.get("s") == []


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_idle_sessions_expire():
    clock = FakeClock()
    store = SessionStore(ttl_seconds=100, clock=clock)
    store.append_turn("s", "q", "r")

    clock.now = 101

    assert store.get("s") == []
    assert len(store) == 0


def test_activity_keeps_a_session_alive():
    clock = FakeClock()
    store = SessionStore(ttl_seconds=100, clock=clock)
    store.append_turn("s", "q", "r")

    clock.now = 80
    assert store.get("s") != []
    clock.now = 160

    assert store.get("s") != []


def test_expiry_only_removes_idle_sessions():
    clock = FakeClock()
    store = SessionStore(ttl_seconds=100, clock=clock)
    store.append_turn("old", "q", "r")
    clock.now = 90
    store.append_turn("fresh", "q", "r")
    clock.now = 150

    assert store.get("old") == []
    assert store.get("fresh") != []


def test_least_recently_used_session_is_evicted_at_capacity():
    clock = FakeClock()
    store = SessionStore(max_sessions=2, clock=clock)
    store.append_turn("a", "q", "r")
    store.append_turn("b", "q", "r")
    store.get("a")
    store.append_turn("c", "q", "r")

    assert len(store) == 2
    assert store.get("b") == []
    assert store.get("a") != []
    assert store.get("c") != []


def test_only_one_turn_per_session_may_be_in_flight():
    store = SessionStore()

    assert store.try_begin_turn("a") is True
    assert store.try_begin_turn("a") is False
    assert store.try_begin_turn("b") is True

    store.end_turn("a")

    assert store.try_begin_turn("a") is True


def test_an_abandoned_turn_lock_expires():
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    store.try_begin_turn("a")

    now[0] = config.TURN_LOCK_SECONDS + 1

    assert store.try_begin_turn("a") is True
