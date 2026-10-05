import os
import sys
from pathlib import Path

import anthropic
import truststore
from dotenv import load_dotenv

# Local antivirus re-signs TLS certs; trust the OS store, not certifi's bundle.
truststore.inject_into_ssl()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
NOTION_TIMEOUT = 30
NOTION_RATE_LIMIT_PER_SEC = 3
NOTION_MAX_RETRIES = 3
NOTION_DEFAULT_RETRY_AFTER = 1.0

QUERY_DEFAULT_LIMIT = 25
QUERY_MAX_LIMIT = 100
PAGE_CONTENT_MAX_CHARS = 20000

CHAT_HISTORY_MAX_MESSAGES = 20
SSE_KEEPALIVE_SECONDS = 15
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"

AGOGE_DATA_SOURCE_ID = "31cca81f-93c9-4783-98ae-fb47fd40e184"
AGOGE_DATABASE_ID = "cabacdef-db2c-455a-9a59-ab6b95d3b896"

AJ_GEBARA_PAGE_ID = "3cafbe79-a388-8024-be47-cd46e51f6f43"


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
