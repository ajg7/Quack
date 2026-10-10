import pytest
import requests

from quack import budget, config, router
from quack.integrations import notion
from quack.integrations.notion import NotionResults
from quack.retrieval import indexer
from quack.retrieval.store import IndexUnavailable
from quack.tools import notion as notion_tools

OLD = "2026-01-01T00:00:00.000Z"
NEW = "2026-02-01T00:00:00.000Z"


def seed(store, page_id="p1", title="Latin notes", edited=OLD, text="sequence of tenses"):
    store.replace_page(page_id, title, f"https://n/{page_id}", edited, [text])
    store.replaced.clear()


def live_page(page_id="p1", edited=OLD, **extra):
    return {"id": page_id, "last_edited_time": edited, "properties": {}, **extra}


def http_error(status):
    response = type("Response", (), {"status_code": status})()
    return requests.exceptions.HTTPError("failed", response=response)


@pytest.fixture
def notion_pages(monkeypatch):
    pages = {}
    fetched = []

    def get_page(page_id, fresh=False):
        fetched.append((page_id, fresh))
        value = pages[page_id]
        if isinstance(value, Exception):
            raise value
        return value

    block = {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "new text about tenses"}]}}
    monkeypatch.setattr(notion, "get_page", get_page)
    monkeypatch.setattr(notion, "get_page_blocks", lambda page_id, fresh=False: NotionResults([block]))
    pages["fetched"] = fetched
    return pages


def test_route_for_uses_the_static_map_and_result_override():
    assert router.route_for("query_database") == router.LIVE
    assert router.route_for("semantic_search") == router.RAG
    assert router.route_for("semantic_search", {"route": router.LIVE_FALLBACK}) == router.LIVE_FALLBACK
    assert router.route_for("mystery") == router.LIVE


def test_fresh_hit_is_returned_with_snippet_and_flag(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = live_page()

    out = router.semantic_search("sequence tenses", store=fake_store)

    assert out["route"] == router.RAG
    assert out["results"][0]["freshness"] == router.FRESH
    assert out["results"][0]["id"] == "p1"
    assert "warning" not in out


def test_freshness_check_bypasses_the_cache(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = live_page()

    router.semantic_search("tenses", store=fake_store)

    assert notion_pages["fetched"] == [("p1", True)]


def test_stale_hit_is_reindexed_and_returned_refreshed(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = live_page(edited=NEW)

    out = router.semantic_search("tenses", store=fake_store)

    assert out["results"][0]["freshness"] == router.REFRESHED
    assert out["results"][0]["last_edited_time"] == NEW
    assert "new text about tenses" in out["results"][0]["snippet"]
    assert fake_store.replaced == ["p1"]


def test_refreshes_are_capped_and_the_rest_marked_stale(fake_store, notion_pages, monkeypatch):
    monkeypatch.setattr(config, "STALE_REFRESH_MAX", 1)
    for pid in ("p1", "p2"):
        seed(fake_store, pid, title=pid, text="tenses")
        notion_pages[pid] = live_page(pid, NEW)

    out = router.semantic_search("tenses", store=fake_store)

    assert sorted(r["freshness"] for r in out["results"]) == [router.REFRESHED, router.STALE]
    assert "out of date" in out["warning"]


def test_deleted_page_is_dropped_and_removed_from_the_index(fake_store, notion_pages):
    seed(fake_store)
    seed(fake_store, "p2", title="Other", text="tenses tenses")
    notion_pages["p1"] = http_error(404)
    notion_pages["p2"] = live_page("p2")

    out = router.semantic_search("tenses", store=fake_store)

    assert [r["id"] for r in out["results"]] == ["p2"]
    assert fake_store.deleted == ["p1"]


def test_trashed_page_is_dropped(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = live_page(in_trash=True)

    out = router.semantic_search("tenses", store=fake_store)

    assert out["results"] == []
    assert fake_store.deleted == ["p1"]


def test_unreachable_notion_marks_hits_unchecked_with_a_warning(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = http_error(500)

    out = router.semantic_search("tenses", store=fake_store)

    assert out["results"][0]["freshness"] == router.UNCHECKED
    assert "out of date" in out["warning"]


def test_exhausted_budget_marks_hits_unchecked(fake_store, notion_pages):
    seed(fake_store)
    notion_pages["p1"] = budget.BudgetExceeded(budget.REQUESTS, 1)

    out = router.semantic_search("tenses", store=fake_store)

    assert out["results"][0]["freshness"] == router.UNCHECKED


def test_failed_reindex_leaves_the_hit_stale(fake_store, notion_pages, monkeypatch):
    seed(fake_store)
    notion_pages["p1"] = live_page(edited=NEW)

    def broken(page, store):
        raise IndexUnavailable("disk")

    monkeypatch.setattr(indexer, "index_page", broken)

    out = router.semantic_search("tenses", store=fake_store)

    assert out["results"][0]["freshness"] == router.STALE


def test_multiple_chunks_of_one_page_collapse_to_one_result(fake_store, notion_pages):
    fake_store.replace_page("p1", "T", "u", OLD, ["tenses a", "tenses b", "tenses c"])
    notion_pages["p1"] = live_page()

    assert router.semantic_search("tenses", store=fake_store)["count"] == 1


def test_limit_is_clamped(fake_store, notion_pages):
    for i in range(15):
        pid = f"p{i}"
        seed(fake_store, pid, title=pid, text="tenses")
        notion_pages[pid] = live_page(pid)

    assert router.semantic_search("tenses", limit=500, store=fake_store)["count"] == config.SEMANTIC_MAX_LIMIT
    assert router.semantic_search("tenses", limit=0, store=fake_store)["count"] == 1


@pytest.fixture
def live_search(monkeypatch):
    seen = {}

    def fake(query, limit=config.SEARCH_DEFAULT_LIMIT):
        seen["args"] = (query, limit)
        return {"results": [{"id": "x", "title": "Latin"}], "truncated": False, "partial": False}

    monkeypatch.setattr(notion_tools, "search_notion", fake)
    return seen


def test_empty_index_falls_back_to_live_search(fake_store, live_search):
    out = router.semantic_search("tenses", store=fake_store)

    assert out["route"] == router.LIVE_FALLBACK
    assert out["index"]["available"] is False
    assert out["results"] == [{"id": "x", "title": "Latin"}]
    assert "keyword" in out["warning"]
    assert live_search["args"] == ("tenses", config.SEMANTIC_DEFAULT_LIMIT)


def test_unavailable_index_falls_back_instead_of_raising(fake_store, live_search):
    fake_store.fail = "chroma exploded"

    out = router.semantic_search("tenses", store=fake_store)

    assert out["route"] == router.LIVE_FALLBACK
    assert "chroma exploded" in out["index"]["reason"]


def test_fallback_keeps_the_live_search_warning(fake_store, monkeypatch):
    monkeypatch.setattr(
        notion_tools,
        "search_notion",
        lambda query, limit=20: {"results": [], "partial": True, "warning": "rate limited"},
    )

    out = router.semantic_search("tenses", store=fake_store)

    assert "keyword" in out["warning"]
    assert "rate limited" in out["warning"]
