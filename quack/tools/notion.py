from quack import budget, config
from quack.integrations import notion

SEARCH_NOTION_SCHEMA = {
    "name": "search_notion",
    "description": (
        "Search by keyword or title across AJ's Notion workspace. Each match comes back with "
        "its id, title, url and last-edited time, but not its contents or property values. "
        "Use it to locate a page or database when you don't know where it lives: a result whose "
        "object is 'data_source' is a database you can pass to query_database, and a result whose "
        "object is 'page' can be passed to get_page. Results under his primary A.J. Gebara hub "
        "page are ranked first, followed by everything else (legacy/archive content). At most "
        f"{config.SEARCH_MAX_LIMIT} matches come back, and 'truncated': true means more matched, so "
        "use a more specific query instead of paging. Not for filtering by property values."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to search for across AJ's Notion workspace"},
            "limit": {
                "type": "integer",
                "description": f"Maximum matches to return (default {config.SEARCH_DEFAULT_LIMIT}, max {config.SEARCH_MAX_LIMIT})",
            },
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

AGGREGATE_DATABASE_SCHEMA = {
    "name": "aggregate_database",
    "description": (
        "Count the rows of one Notion database, optionally grouped by a property, for questions "
        "like 'how many tasks are Done', 'how many tasks does each Odyssey have' or 'which "
        "Ultimate has the most tasks'. It reads every matching row server-side (up to "
        f"{config.AGGREGATE_MAX_ROWS}) and returns only counts, so it works on databases far "
        "larger than query_database's 100-row cap. Pass the id of a search_notion result whose "
        "object is 'data_source' as data_source_id. 'filter' works as in query_database. "
        "'group_by' is an exact property name; select, status, multi_select, checkbox, date and "
        "relation properties work. For relation properties each group value is the id of a related "
        "page: map ids to names with one query_database call on the related database. Rows with "
        "no value are counted under '(none)'. Without group_by only the total comes back. "
        "'truncated': true means more rows exist than were counted. Not for reading row contents "
        "(use query_database)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "data_source_id": {
                "type": "string",
                "description": "The id of a search_notion result whose object is 'data_source'",
            },
            "group_by": {
                "type": "string",
                "description": "Exact property name to count rows by. Omit for a total only.",
            },
            "filter": {
                "type": "object",
                "description": "Notion filter object, as for query_database. Omit to count all rows.",
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


def _clamp_limit(limit: int, maximum: int) -> int:
    return max(1, min(int(limit), maximum))


def _partial_warning(reason: str, action: str, incomplete: str, consequence: str) -> str:
    if reason == notion.BUDGET:
        return (
            f"The Notion request budget for this question was used up, so {incomplete} incomplete. "
            f"{consequence} {budget.STOP_INSTRUCTION}"
        )
    return (
        f"Notion rate-limited this {action} and retries were exhausted, so {incomplete} "
        f"incomplete. {consequence}"
    )


def _plain_text(fragments: list[dict] | None) -> str:
    return "".join(fragment.get("plain_text", "") for fragment in fragments or [])


def object_title(obj: dict) -> str:
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


def search_notion(query: str, limit: int = config.SEARCH_DEFAULT_LIMIT) -> dict:
    limit = _clamp_limit(limit, config.SEARCH_MAX_LIMIT)
    search_results = notion.search(query, limit=limit)

    primary = []
    legacy = []

    for page in search_results.results:
        normalized_page = {
            "object": page.get("object"),
            "id": page.get("id"),
            "title": object_title(page),
            "url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
        }

        is_primary = page.get("parent", {}).get("page_id") == config.AJ_GEBARA_PAGE_ID
        (primary if is_primary else legacy).append(normalized_page)

    truncated = search_results.has_more and not search_results.partial
    output = {
        "results": primary + legacy,
        "truncated": truncated,
        "partial": search_results.partial,
    }

    warnings = []
    if search_results.partial:
        warnings.append(
            _partial_warning(
                search_results.reason,
                "search",
                "these results are",
                "Tell the user the list may be missing items.",
            )
        )
    if truncated:
        warnings.append(
            f"Only the first {len(search_results.results)} matches are shown and more exist. "
            "Tell the user, or search with a more specific query."
        )
    if warnings:
        output["warning"] = " ".join(warnings)
    return output


def query_database(
    data_source_id: str, filter: dict | None = None, limit: int = config.QUERY_DEFAULT_LIMIT
) -> dict:
    limit = _clamp_limit(limit, config.QUERY_MAX_LIMIT)
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
            _partial_warning(
                found.reason,
                "query",
                "the rows are",
                "Tell the user the list may be missing items.",
            )
        )
    if truncated:
        warnings.append(
            f"Only the first {len(rows)} matching rows are shown and more exist. Tell the user, "
            "or narrow the filter."
        )
    if warnings:
        output["warning"] = " ".join(warnings)
    return output


def _group_keys(value) -> list:
    if value is None or value == "" or value == []:
        return ["(none)"]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return [f"{value.get('start')} to {value.get('end')}"]
    return [str(value)]


def aggregate_database(
    data_source_id: str, group_by: str | None = None, filter: dict | None = None
) -> dict:
    found = notion.query_data_source(data_source_id, filter, config.AGGREGATE_MAX_ROWS)
    rows = [normalize_row(page) for page in found.results]
    truncated = found.has_more and not found.partial

    output = {
        "total": len(rows),
        "truncated": truncated,
        "partial": found.partial,
    }

    if group_by:
        if rows and group_by not in rows[0]["properties"]:
            raise ValueError(
                f"Property '{group_by}' not found. Available: {', '.join(sorted(rows[0]['properties']))}"
            )
        counts: dict[str, int] = {}
        for row in rows:
            for key in _group_keys(row["properties"].get(group_by)):
                counts[key] = counts.get(key, 0) + 1
        output["group_by"] = group_by
        output["groups"] = [
            {"value": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    warnings = []
    if found.partial:
        warnings.append(
            _partial_warning(
                found.reason,
                "count",
                "the counts are",
                "Tell the user the numbers are lower bounds.",
            )
        )
    if truncated:
        warnings.append(
            f"Only the first {len(rows)} rows were counted and more exist, so the numbers are lower bounds."
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
        "title": object_title(page),
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": normalize_properties(page.get("properties", {})),
        "content": content,
        "content_truncated": content_truncated,
        "partial": blocks.partial,
    }
    if blocks.partial:
        output["warning"] = _partial_warning(
            blocks.reason, "read", "the content is", "Tell the user the page may be cut off."
        )
    return output


def list_data_sources() -> dict:
    found = notion.search("", {"property": "object", "value": "data_source"})
    sources = sorted(
        ({"id": item.get("id"), "name": object_title(item)} for item in found.results),
        key=lambda source: source["name"].lower(),
    )
    return {"sources": sources, "partial": found.partial}
