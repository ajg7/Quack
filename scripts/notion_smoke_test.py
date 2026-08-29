"""Connectivity check for the Notion API.

Not part of Quack itself. Answers two separate questions:

  1. Is the token valid?            -> GET /v1/users/me
  2. What can the token actually    -> POST /v1/search
     see in the workspace?

Question 2 matters because a Notion token grants access to nothing by
default. You must explicitly connect each page or database to the
integration from inside Notion. A valid token that sees zero data sources
is the normal symptom of having skipped that step.

    python scripts/notion_smoke_test.py
"""

import os
import sys

import requests
import truststore
from dotenv import load_dotenv

# Use the OS certificate store instead of certifi's fixed public-CA bundle.
# Local TLS-inspecting software (antivirus, corporate proxies) re-signs every
# certificate with a private root that is installed in the Windows store but
# is not, and cannot be, in certifi. Without this, requests rejects those
# certificates as unverifiable. Verification stays fully enabled either way --
# this changes which authorities are trusted, never whether we check.
truststore.inject_into_ssl()

API = "https://api.notion.com/v1"

# Pinned deliberately. Notion requires this header on every request and
# changes response shapes between versions -- 2025-09-03 is where databases
# became containers of "data sources", which changed how rows are queried.
NOTION_VERSION = "2026-03-11"

TIMEOUT = 30

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def title_of(item: dict) -> str:
    """Pull a readable title out of a page or data_source object."""
    # data_source objects carry a top-level `title` rich-text array.
    rich = item.get("title") or []
    if rich:
        return "".join(part.get("plain_text", "") for part in rich) or "(untitled)"

    # page objects bury the title inside whichever property has type "title".
    for prop in (item.get("properties") or {}).values():
        if prop.get("type") == "title":
            parts = prop.get("title") or []
            return "".join(p.get("plain_text", "") for p in parts) or "(untitled)"

    return "(untitled)"


def setup_help() -> None:
    print(
        "\nTo connect Notion:\n"
        "  1. Create an internal integration:\n"
        "     https://www.notion.so/my-integrations\n"
        "  2. Copy its Internal Integration Secret into .env as:\n"
        "     NOTION_API_KEY=ntn_...\n"
        "  3. IMPORTANT - open your tasks database in Notion, click the\n"
        "     ... menu (top right) -> Connections -> Connect to -> pick your\n"
        "     integration. The token alone grants no access until you do this."
    )


def main() -> int:
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        print("NOTION_API_KEY is not set in .env.")
        setup_help()
        return 1

    # --- 1. Is the token valid? ------------------------------------------
    print(f"Checking token against Notion API {NOTION_VERSION} ...\n")
    resp = requests.get(f"{API}/users/me", headers=headers(token), timeout=TIMEOUT)

    if resp.status_code == 401:
        print("Token rejected (401). The NOTION_API_KEY in .env is wrong or revoked.")
        setup_help()
        return 1
    if resp.status_code != 200:
        print(f"Unexpected {resp.status_code}: {resp.text[:300]}")
        return 1

    me = resp.json()
    bot = me.get("bot") or {}
    print(f"Token OK  bot={me.get('name')!r}  workspace={bot.get('workspace_name')!r}")

    # --- 2. What can it see? ---------------------------------------------
    # Search returns pages and data_sources -- never database objects, as of
    # the data-sources change. Empty results mean nothing has been shared.
    resp = requests.post(
        f"{API}/search",
        headers=headers(token),
        json={"filter": {"property": "object", "value": "data_source"}, "page_size": 25},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"Search failed {resp.status_code}: {resp.text[:300]}")
        return 1

    results = resp.json().get("results", [])
    if not results:
        print("\nToken is valid but sees 0 data sources.")
        print("That means no database has been connected to the integration yet.")
        setup_help()
        return 1

    print(f"\nVisible data sources ({len(results)}):")
    for item in results:
        print(f"  - {title_of(item)}")
        print(f"      data_source_id: {item.get('id')}")
        parent = item.get("parent") or {}
        if parent.get("type") == "database_id":
            print(f"      database_id:    {parent.get('database_id')}")

    print("\nOK - Notion is reachable and at least one data source is shared.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.exceptions.RequestException as err:
        print(f"Could not reach Notion: {err}")
        sys.exit(1)
