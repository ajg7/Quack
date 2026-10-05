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
