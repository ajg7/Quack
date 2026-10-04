from quack import config
from quack.integrations import notion

SEARCH_NOTION_SCHEMA = {
    "name": "search_notion",
    "description": (
        "Search by keyword or title across AJ's Notion workspace. Results under his primary "
        "A.J. Gebara hub page are ranked first, followed by everything else (legacy/archive "
        "content). Good for locating a page or database when you don't know its exact location "
        "- not for filtering by property values or returning full page content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to search for across AJ's Notion workspace"},
        },
        "required": ["query"],
    },
}

def search_notion(query: str) -> list[dict]:
    raw_results = notion.search(query)

    primary = []
    legacy = []

    for page in raw_results:
        object_type = page.get("object")

        if object_type == "page":
            title_property = next(
                (prop for prop in page.get("properties", {}).values() if prop.get("type") == "title"),
                {},
            )
            title_fragments = title_property.get("title", [])
        else:
            title_fragments = page.get("title", [])

        title = "".join(fragment.get("plain_text", "") for fragment in title_fragments)

        normalized_page = {
            "object": object_type,
            "title": title,
            "url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
        }

        is_primary = page.get("parent", {}).get("page_id") == config.AJ_GEBARA_PAGE_ID
        (primary if is_primary else legacy).append(normalized_page)

    return primary + legacy