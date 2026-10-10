from quack.tools.semantic import SEMANTIC_SEARCH_SCHEMA, semantic_search
from quack.tools.notion import (
    AGGREGATE_DATABASE_SCHEMA,
    aggregate_database,
    GET_PAGE_SCHEMA,
    QUERY_DATABASE_SCHEMA,
    SEARCH_NOTION_SCHEMA,
    get_page,
    query_database,
    search_notion,
)

SCHEMAS = [
    SEARCH_NOTION_SCHEMA,
    QUERY_DATABASE_SCHEMA,
    AGGREGATE_DATABASE_SCHEMA,
    GET_PAGE_SCHEMA,
    SEMANTIC_SEARCH_SCHEMA,
]

HANDLERS = {
    "search_notion": search_notion,
    "query_database": query_database,
    "aggregate_database": aggregate_database,
    "get_page": get_page,
    "semantic_search": semantic_search,
}
