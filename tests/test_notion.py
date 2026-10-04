import json
from pathlib import Path

from quack.integrations.notion import blocks_to_text

FIXTURES = Path(__file__).parent / "fixtures"


def load_blocks():
    with open(FIXTURES / "blocks.json", encoding="utf-8") as f:
        return json.load(f)


def test_blocks_to_text_joins_rich_text_fragments():
    blocks = load_blocks()
    text = blocks_to_text(blocks)
    lines = text.split("\n")

    assert lines[0] == "Agoge"
    assert lines[1] == "Daily rituals live here."
    assert lines[2] == "Read for 20 minutes"


def test_blocks_to_text_skips_empty_and_unsupported_blocks():
    blocks = load_blocks()
    text = blocks_to_text(blocks)

    # the empty paragraph and the divider (no rich_text at all) contribute nothing
    assert text.count("\n") == 2
    assert len(text.split("\n")) == 3


def test_blocks_to_text_empty_input_returns_empty_string():
    assert blocks_to_text([]) == ""
