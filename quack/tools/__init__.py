from quack.tools.notion import SEARCH_NOTION_SCHEMA, search_notion

SCHEMAS = [SEARCH_NOTION_SCHEMA]

HANDLERS = {
    "search_notion": search_notion,
}
