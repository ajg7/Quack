import copy
import json
from pathlib import Path

from quack import config
from quack.integrations.notion import NotionResults
from quack.tools import notion as notion_tools
from quack.tools.notion import SEARCH_NOTION_SCHEMA, search_notion

FIXTURES = Path(__file__).parent / "fixtures"


def load_search_results():
    with open(FIXTURES / "search.json", encoding="utf-8") as f:
        return json.load(f)


def run_search_full(monkeypatch, raw_results, partial=False):
    monkeypatch.setattr(
        notion_tools.notion, "search", lambda query, **kwargs: NotionResults(raw_results, partial=partial)
    )
    return search_notion("anything")


def run_search(monkeypatch, raw_results):
    return run_search_full(monkeypatch, raw_results)["results"]


def by_title(results, title):
    return next(r for r in results if r["title"] == title)


def test_normalized_result_has_only_plain_keys(monkeypatch):
    results = run_search(monkeypatch, load_search_results())

    for result in results:
        assert set(result) == {"object", "id", "title", "url", "last_edited_time"}


def test_results_carry_the_id_other_tools_need(monkeypatch):
    raw = load_search_results()
    results = run_search(monkeypatch, raw)

    assert [r["id"] for r in results] == [item["id"] for item in raw]


def test_data_source_title_comes_from_top_level_title(monkeypatch):
    results = run_search(monkeypatch, load_search_results())

    odysseys = by_title(results, "Odysseys")
    assert odysseys["object"] == "data_source"
    assert odysseys["url"] == "https://app.notion.com/p/385fbe79a388801d90ddc9be21594eec"
    assert odysseys["last_edited_time"] == "2026-09-14T04:31:00.000Z"


def test_page_title_comes_from_title_property(monkeypatch):
    results = run_search(monkeypatch, load_search_results())

    ultimate = by_title(results, "The Ultimate")
    assert ultimate["object"] == "page"
    assert ultimate["last_edited_time"] == "2026-09-06T16:41:00.000Z"


def test_database_row_page_title_is_extracted(monkeypatch):
    results = run_search(monkeypatch, load_search_results())

    assert "Build your own hypervisor" in [r["title"] for r in results]


def test_title_fragments_are_joined(monkeypatch):
    raw = load_search_results()
    page = copy.deepcopy(raw[1])
    title_prop = next(p for p in page["properties"].values() if p["type"] == "title")
    title_prop["title"] = [
        {"plain_text": "Split "},
        {"plain_text": "across "},
        {"plain_text": "fragments"},
    ]

    results = run_search(monkeypatch, [page])

    assert results[0]["title"] == "Split across fragments"


def test_page_without_title_property_gets_empty_title(monkeypatch):
    raw = load_search_results()
    page = copy.deepcopy(raw[1])
    page["properties"] = {}

    results = run_search(monkeypatch, [page])

    assert results[0]["title"] == ""


def test_children_of_primary_page_are_ranked_first(monkeypatch):
    raw = load_search_results()
    legacy_first = copy.deepcopy(raw[2])
    primary_child = copy.deepcopy(raw[1])
    primary_child["parent"] = {"type": "page_id", "page_id": config.AJ_GEBARA_PAGE_ID}

    results = run_search(monkeypatch, [legacy_first, primary_child])

    assert [r["title"] for r in results] == ["The Ultimate", "Build your own hypervisor"]


def test_ranking_preserves_order_within_each_group(monkeypatch):
    raw = load_search_results()
    primary_a = copy.deepcopy(raw[1])
    primary_b = copy.deepcopy(raw[2])
    for page in (primary_a, primary_b):
        page["parent"] = {"type": "page_id", "page_id": config.AJ_GEBARA_PAGE_ID}
    legacy = copy.deepcopy(raw[0])

    results = run_search(monkeypatch, [legacy, primary_a, primary_b])

    assert [r["title"] for r in results] == [
        "The Ultimate",
        "Build your own hypervisor",
        "Odysseys",
    ]


def test_no_primary_children_keeps_original_order(monkeypatch):
    raw = load_search_results()

    results = run_search(monkeypatch, raw)

    assert [r["title"] for r in results] == [
        "Odysseys",
        "The Ultimate",
        "Build your own hypervisor",
    ]


def test_empty_search_returns_empty_list(monkeypatch):
    assert not run_search(monkeypatch, [])


def test_query_is_forwarded_to_notion(monkeypatch):
    seen = []
    monkeypatch.setattr(
        notion_tools.notion, "search", lambda query, **kwargs: seen.append(query) or NotionResults()
    )

    search_notion("agoge rituals")

    assert seen == ["agoge rituals"]


def test_complete_search_is_not_marked_partial(monkeypatch):
    output = run_search_full(monkeypatch, load_search_results())

    assert output["partial"] is False
    assert "warning" not in output


def test_partial_search_carries_flag_and_warning(monkeypatch):
    output = run_search_full(monkeypatch, load_search_results()[:1], partial=True)

    assert output["partial"] is True
    assert "incomplete" in output["warning"]
    assert len(output["results"]) == 1


def test_schema_requires_query():
    schema = SEARCH_NOTION_SCHEMA["input_schema"]

    assert SEARCH_NOTION_SCHEMA["name"] == "search_notion"
    assert schema["required"] == ["query"]
    assert "query" in schema["properties"]
