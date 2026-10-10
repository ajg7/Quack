import json

import pytest

from quack import budget, config
from quack.integrations import notion
from quack.integrations.notion import NotionResults
from quack.retrieval import indexer


def page(page_id, edited, title="Title"):
    return {
        "id": page_id,
        "url": f"https://n/{page_id}",
        "last_edited_time": edited,
        "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}},
        "object": "page",
    }


def block(text):
    return {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": text}]}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path / "traces")
    state = {"listing": NotionResults([]), "blocks": {}, "block_calls": [], "since": []}

    def search_edited_since(since=None):
        state["since"].append(since)
        budget.charge_request()
        return state["listing"]

    def get_page_blocks(page_id, fresh=False):
        budget.charge_request()
        state["block_calls"].append((page_id, fresh))
        value = state["blocks"].get(page_id, NotionResults([block("body")]))
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(notion, "search_edited_since", search_edited_since)
    monkeypatch.setattr(notion, "get_page_blocks", get_page_blocks)
    return state


def test_first_run_indexes_every_page_oldest_first(env, fake_store):
    env["listing"] = NotionResults([page("c", "2026-03"), page("b", "2026-02"), page("a", "2026-01")])

    report = indexer.run(fake_store)

    assert fake_store.replaced == ["a", "b", "c"]
    assert report.pages_found == 3
    assert report.pages_indexed == 3
    assert report.complete is True
    assert report.checkpoint == "2026-03"
    assert indexer.load_checkpoint() == "2026-03"
    assert env["since"] == [None]


def test_request_count_is_one_listing_plus_one_read_per_changed_page(env, fake_store):
    env["listing"] = NotionResults([page("b", "2026-02"), page("a", "2026-01")])

    report = indexer.run(fake_store)

    assert report.notion_requests == 1 + 2
    assert report.chunks_upserted == 2
    assert all(fresh for _, fresh in env["block_calls"])


def test_second_run_starts_from_the_checkpoint_and_skips_unchanged_pages(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])
    indexer.run(fake_store)
    env["block_calls"].clear()

    env["listing"] = NotionResults([page("b", "2026-02"), page("a", "2026-01")])
    report = indexer.run(fake_store)

    assert env["since"][-1] == "2026-01"
    assert report.pages_indexed == 1
    assert report.pages_skipped == 1
    assert [pid for pid, _ in env["block_calls"]] == ["b"]
    assert report.notion_requests == 1 + 1


def test_nothing_changed_costs_one_request(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])
    indexer.run(fake_store)

    report = indexer.run(fake_store)

    assert report.pages_found == 1
    assert report.pages_indexed == 0


def test_full_run_ignores_the_checkpoint(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])
    indexer.run(fake_store)

    indexer.run(fake_store, full=True)

    assert env["since"][-1] is None


def test_limit_processes_the_oldest_pages_and_resumes_later(env, fake_store):
    env["listing"] = NotionResults([page("c", "2026-03"), page("b", "2026-02"), page("a", "2026-01")])

    first = indexer.run(fake_store, limit=2)

    assert fake_store.replaced == ["a", "b"]
    assert first.complete is False
    assert first.checkpoint == "2026-02"

    second = indexer.run(fake_store)

    assert second.pages_indexed == 1
    assert fake_store.replaced == ["a", "b", "c"]


def test_a_failing_page_freezes_the_checkpoint_so_it_is_retried(env, fake_store):
    env["listing"] = NotionResults([page("c", "2026-03"), page("b", "2026-02"), page("a", "2026-01")])
    env["blocks"]["b"] = RuntimeError("403 forbidden")

    report = indexer.run(fake_store)

    assert report.complete is False
    assert "b: RuntimeError" in report.errors[0]
    assert report.checkpoint == "2026-01"
    assert sorted(fake_store.pages) == ["a", "c"]


def test_partial_page_reads_are_not_indexed(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])
    env["blocks"]["a"] = NotionResults([block("half")], partial=True, reason=notion.RATE_LIMIT)

    report = indexer.run(fake_store)

    assert fake_store.pages == {}
    assert report.complete is False
    assert report.checkpoint is None


def test_request_budget_stops_the_run_without_advancing_past_unindexed_pages(env, fake_store, monkeypatch):
    monkeypatch.setattr(config, "INDEX_MAX_REQUESTS", 2)
    env["listing"] = NotionResults([page("c", "2026-03"), page("b", "2026-02"), page("a", "2026-01")])

    report = indexer.run(fake_store)

    assert sorted(fake_store.pages) == ["a"]
    assert report.complete is False
    assert report.checkpoint == "2026-01"


def test_truncated_listing_is_reported_incomplete(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")], partial=True, has_more=True, reason=notion.BUDGET)

    report = indexer.run(fake_store)

    assert report.complete is False
    assert "cut short" in report.errors[0]


def test_unavailable_store_ends_the_run_with_an_error(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])
    fake_store.fail = "disk full"

    report = indexer.run(fake_store)

    assert report.complete is False
    assert "Index unavailable" in report.errors[0]


def test_index_page_stores_title_url_edit_time_and_chunks(env, fake_store):
    env["blocks"]["a"] = NotionResults([block("first"), block("second")])

    indexed = indexer.index_page(page("a", "2026-01", title="Latin"), fake_store)

    assert indexed.title == "Latin"
    assert indexed.text == "first\nsecond"
    assert fake_store.pages["a"] == {
        "title": "Latin",
        "url": "https://n/a",
        "edited": "2026-01",
        "chunks": ["first\nsecond"],
    }


def test_empty_page_still_gets_a_title_only_chunk(env, fake_store):
    env["blocks"]["a"] = NotionResults([])

    indexer.index_page(page("a", "2026-01", title="Only a title"), fake_store)

    assert fake_store.pages["a"]["chunks"] == [""]


def test_run_emits_trace_events(env, fake_store):
    env["listing"] = NotionResults([page("a", "2026-01")])

    report = indexer.run(fake_store)

    lines = (config.TRACE_DIR / "quack.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["event"] for e in events] == ["index_start", "index_page", "index_end"]
    assert {e["request_id"] for e in events} == {report.request_id}
    assert events[-1]["notion_requests"] == 2


def test_missing_or_corrupt_checkpoint_means_full_index(env):
    assert indexer.load_checkpoint() is None
    config.CHROMA_DIR.mkdir(parents=True)
    (config.CHROMA_DIR / indexer.CHECKPOINT_FILE).write_text("{not json", encoding="utf-8")

    assert indexer.load_checkpoint() is None
