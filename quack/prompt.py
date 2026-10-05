from datetime import datetime
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


def load_system_prompt(now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    with open(PROMPT_PATH, encoding="utf-8") as f:
        template = f.read()
    return template.replace("{today}", now.strftime("%A, %Y-%m-%d"))
