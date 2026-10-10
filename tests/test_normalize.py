import json
from pathlib import Path

from quack.tools.notion import normalize_properties, normalize_row

FIXTURES = Path(__file__).parent / "fixtures"


def load_rows():
    with open(FIXTURES / "odysseys_rows.json", encoding="utf-8") as f:
        return json.load(f)


def test_real_row_normalizes_to_plain_values():
    for row in load_rows():
        props = normalize_properties(row["properties"])

        assert set(props) == {"Ultimate", "Year", "Status", "Notes", "Pillar", "Month", "Task"}
        assert isinstance(props["Task"], str) and props["Task"]
        assert props["Status"] in {"Not started", "In progress", "Done"}
        assert isinstance(props["Notes"], str)


def test_real_row_select_values_are_names_or_none():
    for row in load_rows():
        raw = row["properties"]
        props = normalize_properties(raw)

        for name in ("Ultimate", "Year", "Pillar", "Month"):
            expected = raw[name]["select"]["name"] if raw[name]["select"] else None
            assert props[name] == expected


def test_real_row_title_matches_plain_text_of_fragments():
    for row in load_rows():
        fragments = row["properties"]["Task"]["title"]
        expected = "".join(f["plain_text"] for f in fragments)

        assert normalize_properties(row["properties"])["Task"] == expected


def test_normalized_row_keeps_id_url_and_edit_time():
    row = load_rows()[0]

    normalized = normalize_row(row)

    assert set(normalized) == {"id", "url", "last_edited_time", "properties"}
    assert normalized["id"] == row["id"]
    assert normalized["url"] == row["url"]


def test_normalized_output_is_json_serializable():
    for row in load_rows():
        json.dumps(normalize_row(row))


def test_multi_select_checkbox_number_url():
    props = normalize_properties(
        {
            "Tags": {"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]},
            "Done": {"type": "checkbox", "checkbox": True},
            "Count": {"type": "number", "number": 3.5},
            "Link": {"type": "url", "url": "https://example.com"},
            "NoLink": {"type": "url", "url": None},
        }
    )

    assert props == {
        "Tags": ["a", "b"],
        "Done": True,
        "Count": 3.5,
        "Link": "https://example.com",
        "NoLink": None,
    }


def test_date_single_range_and_empty():
    props = normalize_properties(
        {
            "One": {"type": "date", "date": {"start": "2026-10-04", "end": None}},
            "Range": {"type": "date", "date": {"start": "2026-10-04", "end": "2026-10-09"}},
            "Empty": {"type": "date", "date": None},
        }
    )

    assert props["One"] == "2026-10-04"
    assert props["Range"] == {"start": "2026-10-04", "end": "2026-10-09"}
    assert props["Empty"] is None


def test_relation_people_files_and_timestamps():
    props = normalize_properties(
        {
            "Rel": {"type": "relation", "relation": [{"id": "r1"}, {"id": "r2"}], "has_more": False},
            "Who": {"type": "people", "people": [{"id": "u1", "name": "AJ"}, {"id": "u2"}]},
            "Files": {"type": "files", "files": [{"name": "a.pdf"}]},
            "Created": {"type": "created_time", "created_time": "2026-01-01T00:00:00.000Z"},
            "By": {"type": "created_by", "created_by": {"id": "u1", "name": "AJ"}},
        }
    )

    assert props == {
        "Rel": ["r1", "r2"],
        "Who": ["AJ", "u2"],
        "Files": ["a.pdf"],
        "Created": "2026-01-01T00:00:00.000Z",
        "By": "AJ",
    }


def test_unique_id_and_formula():
    props = normalize_properties(
        {
            "ID": {"type": "unique_id", "unique_id": {"prefix": "ODY", "number": 12}},
            "Bare": {"type": "unique_id", "unique_id": {"prefix": None, "number": 7}},
            "F": {"type": "formula", "formula": {"type": "string", "string": "hello"}},
            "FN": {"type": "formula", "formula": {"type": "number", "number": 4}},
        }
    )

    assert props == {"ID": "ODY-12", "Bare": 7, "F": "hello", "FN": 4}


def test_unsupported_types_are_omitted():
    props = normalize_properties(
        {
            "Roll": {"type": "rollup", "rollup": {"type": "number", "number": 2}},
            "Keep": {"type": "checkbox", "checkbox": False},
        }
    )

    assert props == {"Keep": False}


def test_empty_properties():
    assert not normalize_properties({})
    assert not normalize_row({"id": "x"})["properties"]
