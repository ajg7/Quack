from quack.cache import TTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_get_returns_a_stored_value():
    cache = TTLCache(60, 10)
    cache.put("a", {"x": 1})

    assert cache.get("a") == {"x": 1}


def test_missing_key_returns_none():
    assert TTLCache(60, 10).get("nope") is None


def test_entries_expire_after_the_ttl():
    clock = Clock()
    cache = TTLCache(60, 10, clock)
    cache.put("a", 1)

    clock.now = 59
    assert cache.get("a") == 1

    clock.now = 61
    assert cache.get("a") is None
    assert len(cache) == 0


def test_oldest_entry_is_evicted_beyond_the_size_cap():
    cache = TTLCache(60, 2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)

    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_mutating_a_returned_value_does_not_change_the_cache():
    cache = TTLCache(60, 10)
    cache.put("a", {"items": [1]})

    cache.get("a")["items"].append(2)

    assert cache.get("a") == {"items": [1]}


def test_mutating_the_stored_original_does_not_change_the_cache():
    cache = TTLCache(60, 10)
    value = {"items": [1]}
    cache.put("a", value)
    value["items"].append(2)

    assert cache.get("a") == {"items": [1]}


def test_zero_ttl_disables_caching():
    cache = TTLCache(0, 10)
    cache.put("a", 1)

    assert cache.get("a") is None


def test_clear_empties_the_cache():
    cache = TTLCache(60, 10)
    cache.put("a", 1)
    cache.clear()

    assert len(cache) == 0
