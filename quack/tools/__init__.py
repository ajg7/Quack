from quack.tools.notion import (
    GET_PAGE_SCHEMA,
    QUERY_DATABASE_SCHEMA,
    SEARCH_NOTION_SCHEMA,
    get_page,
    query_database,
    search_notion,
)

SCHEMAS = [SEARCH_NOTION_SCHEMA, QUERY_DATABASE_SCHEMA, GET_PAGE_SCHEMA]

HANDLERS = {
    "search_notion": search_notion,
    "query_database": query_database,
    "get_page": get_page,
}
