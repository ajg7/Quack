from quack import budget, config
from quack.integrations import notion
from quack.integrations.notion import NotionResults
from quack.tools import notion as notion_tools
from quack.tools.notion import SEARCH_NOTION_SCHEMA, get_page, query_database, search_notion


def stub_search(monkeypatch, results):
    seen = {}

    def fake(query, filters=None, limit=None):
        seen["limit"] = limit
        return results

    monkeypatch.setattr(notion_tools.notion, "search", fake)
    return seen


def test_search_uses_the_default_limit(monkeypatch):
    seen = stub_search(monkeypatch, NotionResults())

    search_notion("x")

    assert seen["limit"] == config.SEARCH_DEFAULT_LIMIT


def test_search_clamps_the_limit(monkeypatch):
    seen = stub_search(monkeypatch, NotionResults())

    search_notion("x", limit=10_000)
    assert seen["limit"] == config.SEARCH_MAX_LIMIT

    search_notion("x", limit=0)
    assert seen["limit"] == 1


def test_search_flags_truncation_and_warns(monkeypatch):
    stub_search(monkeypatch, NotionResults([{"id": "1"}, {"id": "2"}], has_more=True))

    output = search_notion("x")

    assert output["truncated"] is True
    assert output["partial"] is False
    assert "more exist" in output["warning"]


def test_complete_search_is_not_truncated(monkeypatch):
    stub_search(monkeypatch, NotionResults([{"id": "1"}]))

    output = search_notion("x")

    assert output["truncated"] is False
    assert "warning" not in output


def test_partial_search_is_not_also_called_truncated(monkeypatch):
    stub_search(monkeypatch, NotionResults([{"id": "1"}], partial=True, has_more=True))

    assert search_notion("x")["truncated"] is False


def test_budget_partial_warning_tells_the_model_to_stop(monkeypatch):
    stub_search(
        monkeypatch,
        NotionResults([{"id": "1"}], partial=True, has_more=True, reason=notion.BUDGET),
    )

    warning = search_notion("x")["warning"]

    assert "budget" in warning
    assert budget.STOP_INSTRUCTION in warning


def test_rate_limit_partial_warning_keeps_its_wording(monkeypatch):
    stub_search(
        monkeypatch,
        NotionResults([{"id": "1"}], partial=True, has_more=True, reason=notion.RATE_LIMIT),
    )

    warning = search_notion("x")["warning"]

    assert "rate-limited" in warning
    assert budget.STOP_INSTRUCTION not in warning


def test_query_database_budget_partial_warning(monkeypatch):
    monkeypatch.setattr(
        notion_tools.notion,
        "query_data_source",
        lambda *a, **k: NotionResults([], partial=True, has_more=True, reason=notion.BUDGET),
    )

    output = query_database("ds")

    assert output["partial"] is True
    assert budget.STOP_INSTRUCTION in output["warning"]


def test_get_page_budget_partial_warning(monkeypatch):
    monkeypatch.setattr(notion_tools.notion, "get_page", lambda page_id: {"id": page_id})
    monkeypatch.setattr(
        notion_tools.notion,
        "get_page_blocks",
        lambda page_id: NotionResults([], partial=True, reason=notion.BUDGET),
    )

    assert budget.STOP_INSTRUCTION in get_page("p")["warning"]


def test_search_schema_exposes_limit_but_keeps_query_required():
    schema = SEARCH_NOTION_SCHEMA["input_schema"]

    assert "limit" in schema["properties"]
    assert schema["required"] == ["query"]
