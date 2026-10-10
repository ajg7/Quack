import pytest

from quack import budget, config
from quack.integrations import notion
from quack.integrations.notion import NotionResults
from quack.tools import notion as notion_tools
from quack.tools.notion import aggregate_database


def row(**properties):
    typed = {}
    for name, value in properties.items():
        if isinstance(value, bool):
            typed[name] = {"type": "checkbox", "checkbox": value}
        elif isinstance(value, list):
            typed[name] = {"type": "relation", "relation": [{"id": v} for v in value]}
        elif value is None:
            typed[name] = {"type": "select", "select": None}
        else:
            typed[name] = {"type": "select", "select": {"name": value}}
    return {"id": "r", "url": "u", "last_edited_time": "t", "properties": typed}


@pytest.fixture
def source(monkeypatch):
    state = {"results": NotionResults([]), "calls": []}

    def fake(data_source_id, filters=None, limit=None):
        state["calls"].append({"id": data_source_id, "filter": filters, "limit": limit})
        return state["results"]

    monkeypatch.setattr(notion_tools.notion, "query_data_source", fake)
    return state


def test_total_only_without_group_by(source):
    source["results"] = NotionResults([row(Status="Todo")] * 3)

    out = aggregate_database("ds")

    assert out == {"total": 3, "truncated": False, "partial": False}


def test_counts_a_select_property_most_common_first(source):
    source["results"] = NotionResults(
        [row(Status="Todo"), row(Status="Done"), row(Status="Todo"), row(Status=None)]
    )

    out = aggregate_database("ds", group_by="Status")

    assert out["groups"][0] == {"value": "Todo", "count": 2}
    assert {g["value"]: g["count"] for g in out["groups"]} == {"Todo": 2, "Done": 1, "(none)": 1}


def test_relation_rows_count_toward_every_linked_page(source):
    source["results"] = NotionResults(
        [row(Odyssey=["a"]), row(Odyssey=["a", "b"]), row(Odyssey=[])]
    )

    out = aggregate_database("ds", group_by="Odyssey")

    assert {g["value"]: g["count"] for g in out["groups"]} == {"a": 2, "b": 1, "(none)": 1}
    assert out["groups"][0] == {"value": "a", "count": 2}


def test_checkbox_values_are_grouped_as_text(source):
    source["results"] = NotionResults([row(Done=True), row(Done=False), row(Done=True)])

    out = aggregate_database("ds", group_by="Done")

    assert {g["value"]: g["count"] for g in out["groups"]} == {"True": 2, "False": 1}


def test_unknown_group_property_names_the_available_ones(source):
    source["results"] = NotionResults([row(Status="Todo", Day="Monday")])

    with pytest.raises(ValueError, match="Available: Day, Status"):
        aggregate_database("ds", group_by="Nope")


def test_filter_and_row_cap_are_forwarded(source):
    flt = {"property": "Status", "select": {"equals": "Todo"}}

    aggregate_database("ds", filter=flt)

    assert source["calls"] == [{"id": "ds", "filter": flt, "limit": config.AGGREGATE_MAX_ROWS}]


def test_truncation_is_flagged_as_a_lower_bound(source):
    source["results"] = NotionResults([row(Status="Todo")], has_more=True)

    out = aggregate_database("ds")

    assert out["truncated"] is True
    assert "lower bounds" in out["warning"]


def test_budget_partial_tells_the_model_to_stop(source):
    source["results"] = NotionResults([row(Status="Todo")], partial=True, has_more=True, reason=notion.BUDGET)

    out = aggregate_database("ds")

    assert out["partial"] is True
    assert budget.STOP_INSTRUCTION in out["warning"]


def test_empty_database_counts_zero(source):
    out = aggregate_database("ds", group_by="Status")

    assert out["total"] == 0
    assert out["groups"] == []
