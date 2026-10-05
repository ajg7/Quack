from quack import config
from quack.integrations import notion

SEARCH_NOTION_SCHEMA = {
    "name": "search_notion",
    "description": (
        "Search by keyword or title across AJ's Notion workspace. Each match comes back with "
        "its id, title, url and last-edited time, but not its contents or property values. "
        "Use it to locate a page or database when you don't know where it lives: a result whose "
        "object is 'data_source' is a database you can pass to query_database, and a result whose "
        "object is 'page' can be passed to get_page. Results under his primary A.J. Gebara hub "
        "page are ranked first, followed by everything else (legacy/archive content). Not for "
        "filtering by property values."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to search for across AJ's Notion workspace"},
        },
        "required": ["query"],
    },
}

QUERY_DATABASE_SCHEMA = {
    "name": "query_database",
    "description": (
        "List or filter the rows of one Notion database by property values, for questions like "
        "'which Odysseys are In progress' or 'which tasks have no Month set'. Pass the id of a "
        "search_notion result whose object is 'data_source' as data_source_id. Each row comes back "
        "with its id, url and all of its properties as plain values, so short text fields need no "
        "further call. Property names are exact and case-sensitive; if you don't know them, call "
        "once with no filter and a limit of 3 to see a row's properties. At most 100 rows come back "
        "per call, and 'truncated': true means more rows matched than were returned, so narrow the "
        "filter instead of paging. Not for keyword search across the workspace (use search_notion) "
        "or for a page's body text (use get_page).\n\n"
        "The filter is a Notion filter object. Examples:\n"
        "{\"property\": \"Month\", \"select\": {\"equals\": \"October\"}}\n"
        "{\"property\": \"Status\", \"status\": {\"equals\": \"In progress\"}}\n"
        "{\"property\": \"Task\", \"title\": {\"contains\": \"encryption\"}}\n"
        "{\"property\": \"Month\", \"select\": {\"is_empty\": true}}\n"
        "{\"and\": [{\"property\": \"Status\", \"status\": {\"equals\": \"Not started\"}}, "
        "{\"property\": \"Year\", \"select\": {\"equals\": \"2027\"}}]}\n"
        "The key after \"property\" must match the property's type: select, status, multi_select, "
        "title, rich_text, checkbox, number or date. Combine conditions with \"and\" or \"or\"."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "data_source_id": {
                "type": "string",
                "description": "The id of a search_notion result whose object is 'data_source'",
            },
            "filter": {
                "type": "object",
                "description": "Notion filter object. Omit to list rows without filtering.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum rows to return (default {config.QUERY_DEFAULT_LIMIT}, max {config.QUERY_MAX_LIMIT})",
            },
        },
        "required": ["data_source_id"],
    },
}

GET_PAGE_SCHEMA = {
    "name": "get_page",
    "description": (
        "Read one Notion page in full: its properties as plain values plus its body text. Pass a "
        "page id from a search_notion result whose object is 'page', or from a query_database row. "
        "Use it when the question is about what a page says. Not for finding pages (use "
        "search_notion) or for filtering many rows (use query_database). Very long bodies are cut "
        f"off at about {config.PAGE_CONTENT_MAX_CHARS} characters and flagged with "
        "'content_truncated'. Only paragraph-style text is returned; nested blocks are not."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page_id": {"type": "string", "description": "The id of the page to read"},
        },
        "required": ["page_id"],
    },
}

_UNSUPPORTED = object()


def _plain_text(fragments: list[dict] | None) -> str:
    return "".join(fragment.get("plain_text", "") for fragment in fragments or [])


def _object_title(obj: dict) -> str:
    if obj.get("object") == "page":
        title_property = next(
            (prop for prop in obj.get("properties", {}).values() if prop.get("type") == "title"),
            {},
        )
        return _plain_text(title_property.get("title"))
    return _plain_text(obj.get("title"))


def _normalize_property(prop: dict):
    kind = prop.get("type")
    value = prop.get(kind)

    if kind in ("title", "rich_text"):
        return _plain_text(value)
    if kind in ("select", "status"):
        return value.get("name") if value else None
    if kind == "multi_select":
        return [option.get("name") for option in value or []]
    if kind in ("checkbox", "number", "string", "boolean", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return value
    if kind == "date":
        if not value:
            return None
        if value.get("end"):
            return {"start": value.get("start"), "end": value.get("end")}
        return value.get("start")
    if kind == "people":
        return [person.get("name") or person.get("id") for person in value or []]
    if kind in ("created_by", "last_edited_by"):
        return (value or {}).get("name") or (value or {}).get("id")
    if kind == "relation":
        return [related.get("id") for related in value or []]
    if kind == "files":
        return [file.get("name") for file in value or []]
    if kind == "unique_id":
        if not value:
            return None
        prefix = value.get("prefix")
        return f"{prefix}-{value.get('number')}" if prefix else value.get("number")
    if kind == "formula":
        if not value:
            return None
        return _normalize_property({"type": value.get("type"), value.get("type"): value.get(value.get("type"))})
    return _UNSUPPORTED


def normalize_properties(properties: dict) -> dict:
    normalized = {}
    for name, prop in properties.items():
        value = _normalize_property(prop)
        if value is not _UNSUPPORTED:
            normalized[name] = value
    return normalized


def normalize_row(page: dict) -> dict:
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": normalize_properties(page.get("properties", {})),
    }


def search_notion(query: str) -> dict:
    search_results = notion.search(query)

    primary = []
    legacy = []

    for page in search_results.results:
        normalized_page = {
            "object": page.get("object"),
            "id": page.get("id"),
            "title": _object_title(page),
            "url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
        }

        is_primary = page.get("parent", {}).get("page_id") == config.AJ_GEBARA_PAGE_ID
        (primary if is_primary else legacy).append(normalized_page)

    output = {"results": primary + legacy, "partial": search_results.partial}
    if search_results.partial:
        output["warning"] = (
            "Notion rate-limited this search and retries were exhausted, so these results "
            "are incomplete. Tell the user the list may be missing items."
        )
    return output


def query_database(
    data_source_id: str, filter: dict | None = None, limit: int = config.QUERY_DEFAULT_LIMIT
) -> dict:
    limit = max(1, min(int(limit), config.QUERY_MAX_LIMIT))
    found = notion.query_data_source(data_source_id, filter, limit)

    rows = [normalize_row(page) for page in found.results]
    truncated = found.has_more and not found.partial

    output = {
        "results": rows,
        "count": len(rows),
        "truncated": truncated,
        "partial": found.partial,
    }

    warnings = []
    if found.partial:
        warnings.append(
            "Notion rate-limited this query and retries were exhausted, so the rows are "
            "incomplete. Tell the user the list may be missing items."
        )
    if truncated:
        warnings.append(
            f"Only the first {len(rows)} matching rows are shown and more exist. Tell the user, "
            "or narrow the filter."
        )
    if warnings:
        output["warning"] = " ".join(warnings)
    return output


def get_page(page_id: str) -> dict:
    page = notion.get_page(page_id)
    blocks = notion.get_page_blocks(page_id)

    content = notion.blocks_to_text(blocks.results)
    content_truncated = len(content) > config.PAGE_CONTENT_MAX_CHARS
    if content_truncated:
        content = content[: config.PAGE_CONTENT_MAX_CHARS]

    output = {
        "id": page.get("id"),
        "title": _object_title(page),
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": normalize_properties(page.get("properties", {})),
        "content": content,
        "content_truncated": content_truncated,
        "partial": blocks.partial,
    }
    if blocks.partial:
        output["warning"] = (
            "Notion rate-limited this read and retries were exhausted, so the content is "
            "incomplete. Tell the user the page may be cut off."
        )
    return output


def list_data_sources() -> dict:
    found = notion.search("", {"property": "object", "value": "data_source"})
    sources = sorted(
        ({"id": item.get("id"), "name": _object_title(item)} for item in found.results),
        key=lambda source: source["name"].lower(),
    )
    return {"sources": sources, "partial": found.partial}
