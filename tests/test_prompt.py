from datetime import datetime

from quack.prompt import load_system_prompt


def test_prompt_contains_todays_date_and_weekday():
    prompt = load_system_prompt(datetime(2026, 10, 4, 9, 30))

    assert "Sunday, 2026-10-04" in prompt


def test_prompt_has_no_unfilled_placeholder():
    assert "{today}" not in load_system_prompt()


def test_prompt_keeps_the_tool_guidance():
    prompt = load_system_prompt()

    for tool in ("search_notion", "query_database", "get_page"):
        assert tool in prompt
