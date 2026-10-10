from quack import config

SEMANTIC_SEARCH_SCHEMA = {
    "name": "semantic_search",
    "description": (
        "Find pages by meaning rather than by exact words, for fuzzy questions like 'where did I "
        "write about the sequence of tenses' or 'notes on discipline'. It searches an index of "
        "page contents and returns the best-matching pages with a text snippet, url, last-edited "
        "time and a 'freshness' flag: 'fresh' and 'refreshed' mean the snippet matches Notion "
        "now, while 'stale' or 'unchecked' mean it may be outdated, so read the page with "
        "get_page before quoting details. If the index is unavailable the result has route "
        "'live_fallback' and holds plain keyword matches instead. Snippets are short excerpts, "
        "not whole pages. Not for filtering by property values (use query_database) or for "
        f"locating a page by its exact title (use search_notion). At most {config.SEMANTIC_MAX_LIMIT} "
        "pages come back."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A natural-language description of what to find",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum pages to return (default {config.SEMANTIC_DEFAULT_LIMIT}, max {config.SEMANTIC_MAX_LIMIT})",
            },
        },
        "required": ["query"],
    },
}


def semantic_search(query: str, limit: int = config.SEMANTIC_DEFAULT_LIMIT) -> dict:
    from quack import router

    return router.semantic_search(query, limit)
