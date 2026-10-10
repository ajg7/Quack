import requests

from quack import budget, config
from quack.integrations import notion
from quack.retrieval import indexer
from quack.retrieval.store import Hit, IndexUnavailable, get_store
from quack.tools import notion as notion_tools

LIVE = "live"
RAG = "rag"
LIVE_FALLBACK = "live_fallback"

FRESH = "fresh"
REFRESHED = "refreshed"
STALE = "stale"
UNCHECKED = "unchecked"

TOOL_ROUTES = {
    "search_notion": LIVE,
    "query_database": LIVE,
    "aggregate_database": LIVE,
    "get_page": LIVE,
    "semantic_search": RAG,
}


def route_for(tool: str, result: object = None) -> str:
    if isinstance(result, dict) and result.get("route"):
        return result["route"]
    return TOOL_ROUTES.get(tool, LIVE)


def _is_gone(page: dict) -> bool:
    return bool(page.get("in_trash") or page.get("archived"))


def _status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def _best_per_page(hits: list[Hit], limit: int) -> list[Hit]:
    best: dict[str, Hit] = {}
    for hit in hits:
        if hit.page_id not in best:
            best[hit.page_id] = hit
    return list(best.values())[:limit]


def _check_freshness(hit: Hit, refreshes_left: int, query: str, store) -> tuple[Hit | None, str, int]:
    try:
        page = notion.get_page(hit.page_id, fresh=True)
    except budget.BudgetExceeded:
        return hit, UNCHECKED, refreshes_left
    except requests.exceptions.HTTPError as e:
        if _status(e) in (403, 404):
            store.delete_page(hit.page_id)
            return None, STALE, refreshes_left
        return hit, UNCHECKED, refreshes_left
    except Exception:
        return hit, UNCHECKED, refreshes_left

    if _is_gone(page):
        store.delete_page(hit.page_id)
        return None, STALE, refreshes_left

    if page.get("last_edited_time", "") <= hit.last_edited_time:
        return hit, FRESH, refreshes_left

    if refreshes_left <= 0:
        return hit, STALE, refreshes_left

    try:
        indexer.index_page(page, store)
        refreshed = store.query(query, 1, page_id=hit.page_id)
    except (IndexUnavailable, indexer.IncompletePage, budget.BudgetExceeded):
        return hit, STALE, refreshes_left - 1
    return (refreshed[0] if refreshed else hit), REFRESHED, refreshes_left - 1


def _snippet(text: str) -> str:
    text = text.strip()
    limit = config.SEMANTIC_SNIPPET_CHARS
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _fallback(query: str, limit: int, reason: str) -> dict:
    live = notion_tools.search_notion(query, limit=limit)
    warning = (
        f"The semantic index is not available ({reason}), so these are keyword matches on titles "
        "from a live search, not matches by meaning. Say so in your answer."
    )
    live["warning"] = f"{warning} {live['warning']}" if live.get("warning") else warning
    return {"route": LIVE_FALLBACK, "index": {"available": False, "reason": reason}, **live}


def semantic_search(query: str, limit: int = config.SEMANTIC_DEFAULT_LIMIT, store=None) -> dict:
    limit = max(1, min(int(limit), config.SEMANTIC_MAX_LIMIT))
    store = store or get_store()

    try:
        hits = store.query(query, limit * 3)
    except IndexUnavailable as e:
        return _fallback(query, limit, str(e)[:200])

    if not hits:
        return _fallback(query, limit, "the index is empty; run `python -m quack index`")

    results = []
    refreshes_left = config.STALE_REFRESH_MAX
    for hit in _best_per_page(hits, limit):
        checked, freshness, refreshes_left = _check_freshness(hit, refreshes_left, query, store)
        if checked is None:
            continue
        results.append(
            {
                "id": checked.page_id,
                "title": checked.title,
                "url": checked.url,
                "snippet": _snippet(checked.text),
                "last_edited_time": checked.last_edited_time,
                "freshness": freshness,
                "distance": round(checked.distance, 4),
            }
        )

    output = {
        "route": RAG,
        "results": results,
        "count": len(results),
        "partial": False,
        "index": {"available": True},
    }
    doubtful = [r["title"] for r in results if r["freshness"] in (STALE, UNCHECKED)]
    if doubtful:
        output["warning"] = (
            "These results may be out of date: "
            + ", ".join(doubtful)
            + ". Read them with get_page before relying on their details, or tell the user."
        )
    return output
