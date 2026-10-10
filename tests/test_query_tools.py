import json
from pathlib import Path

from quack import config
from quack.integrations.notion import NotionResults
from quack.tools import HANDLERS, SCHEMAS
from quack.tools import notion as notion_tools
from quack.tools.notion import get_page, query_database

FIXTURES = Path(__file__).parent / "fixtures"


def load_rows():
    with open(FIXTURES / "odysseys_rows.json", encoding="utf-8") as f:
        return json.load(f)


def patch_query(monkeypatch, results, partial=False, has_more=False):
    calls = []

    def fake(data_source_id, filters=None, limit=None):
        calls.append({"id": data_source_id, "filter": filters, "limit": limit})
        return NotionResults(results, partial=partial, has_more=has_more)

    monkeypatch.setattr(notion_tools.notion, "query_data_source", fake)
    return calls


def test_registry_has_five_tools_with_matching_handlers():
    names = [schema["name"] for schema in SCHEMAS]

    assert names == [
        "search_notion",
        "query_database",
        "aggregate_database",
        "get_page",
        "semantic_search",
    ]
    assert set(HANDLERS) == set(names)


def test_every_schema_requires_its_key_argument():
    required = {s["name"]: s["input_schema"]["required"] for s in SCHEMAS}

    assert required == {
        "search_notion": ["query"],
        "query_database": ["data_source_id"],
        "aggregate_database": ["data_source_id"],
        "get_page": ["page_id"],
        "semantic_search": ["query"],
    }


def test_query_database_normalizes_rows(monkeypatch):
    patch_query(monkeypatch, load_rows())

    out = query_database("ds1")

    assert out["count"] == len(load_rows())
    assert set(out["results"][0]) == {"id", "url", "last_edited_time", "properties"}
    assert isinstance(out["results"][0]["properties"]["Task"], str)
    assert out["truncated"] is False
    assert out["partial"] is False
    assert "warning" not in out
    json.dumps(out)


def test_query_database_forwards_filter_and_default_limit(monkeypatch):
    calls = patch_query(monkeypatch, [])
    flt = {"property": "Month", "select": {"equals": "October"}}

    query_database("ds1", flt)

    assert calls == [{"id": "ds1", "filter": flt, "limit": config.QUERY_DEFAULT_LIMIT}]


def test_query_database_clamps_limit(monkeypatch):
    calls = patch_query(monkeypatch, [])

    query_database("ds1", limit=100000)
    query_database("ds1", limit=0)

    assert [c["limit"] for c in calls] == [config.QUERY_MAX_LIMIT, 1]


def test_query_database_flags_truncation(monkeypatch):
    patch_query(monkeypatch, load_rows(), has_more=True)

    out = query_database("ds1")

    assert out["truncated"] is True
    assert out["partial"] is False
    assert "more exist" in out["warning"]


def test_query_database_flags_partial_not_truncated(monkeypatch):
    patch_query(monkeypatch, load_rows()[:1], partial=True, has_more=True)

    out = query_database("ds1")

    assert out["partial"] is True
    assert out["truncated"] is False
    assert "incomplete" in out["warning"]


def patch_page(monkeypatch, page, blocks, partial=False):
    monkeypatch.setattr(notion_tools.notion, "get_page", lambda page_id: page)
    monkeypatch.setattr(
        notion_tools.notion, "get_page_blocks", lambda page_id: NotionResults(blocks, partial=partial)
    )


def text_block(text):
    return {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": text}]}}


def test_get_page_returns_title_properties_and_content(monkeypatch):
    page = load_rows()[0]
    patch_page(monkeypatch, page, [text_block("First line"), text_block("Second line")])

    out = get_page(page["id"])

    assert out["id"] == page["id"]
    assert out["title"] == out["properties"]["Task"]
    assert out["content"] == "First line\nSecond line"
    assert out["content_truncated"] is False
    assert out["partial"] is False
    json.dumps(out)


def test_get_page_truncates_long_content(monkeypatch):
    page = load_rows()[0]
    long_text = "x" * (config.PAGE_CONTENT_MAX_CHARS + 500)
    patch_page(monkeypatch, page, [text_block(long_text)])

    out = get_page(page["id"])

    assert len(out["content"]) == config.PAGE_CONTENT_MAX_CHARS
    assert out["content_truncated"] is True


def test_get_page_with_no_blocks_has_empty_content(monkeypatch):
    page = load_rows()[0]
    patch_page(monkeypatch, page, [])

    assert get_page(page["id"])["content"] == ""


def test_get_page_flags_partial_blocks(monkeypatch):
    page = load_rows()[0]
    patch_page(monkeypatch, page, [text_block("only some")], partial=True)

    out = get_page(page["id"])

    assert out["partial"] is True
    assert "cut off" in out["warning"]
