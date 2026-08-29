import os
import sys

import anthropic
import truststore
from dotenv import load_dotenv

# Local antivirus re-signs TLS certs; trust the OS store, not certifi's bundle.
truststore.inject_into_ssl()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
NOTION_TIMEOUT = 30

AGONS_DATA_SOURCE_ID = "a23b7da0-e8f4-4a21-a648-e810261410a0"
AGONS_DATABASE_ID = "632e329c-fa87-4ea9-bc9f-9868f6b5705e"


class ConfigError(RuntimeError):
    pass


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def anthropic_client() -> anthropic.Anthropic:
    require("ANTHROPIC_API_KEY")
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        return anthropic.Anthropic(
            default_headers={"anthropic-workspace-id": workspace_id}
        )
    return anthropic.Anthropic()


def notion_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {require('NOTION_API_KEY')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
