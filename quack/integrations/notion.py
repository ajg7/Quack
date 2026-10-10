import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from quack import budget, config
from quack.cache import TTLCache

RATE_LIMIT = "rate_limit"
BUDGET = "budget"


@dataclass
class NotionResults:
  results: list[dict] = field(default_factory=list)
  partial: bool = False
  has_more: bool = False
  reason: str = ""


class NotionRateLimitError(Exception):
  pass


class RateLimiter:
  def __init__(self, rate_per_sec: float) -> None:
    self._min_interval = 1.0 / rate_per_sec
    self._last_request: float | None = None
    self._lock = threading.Lock()

  def acquire(self) -> None:
    with self._lock:
      if self._last_request is not None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
          time.sleep(wait)
      self._last_request = time.monotonic()


_limiter = RateLimiter(config.NOTION_RATE_LIMIT_PER_SEC)
_cache = TTLCache(config.NOTION_CACHE_TTL_SECONDS, config.NOTION_CACHE_MAX_ENTRIES)


def clear_cache() -> None:
  _cache.clear()


def _cache_key(method: str, path: str, kwargs: dict) -> str:
  return json.dumps([method, path, kwargs.get("params"), kwargs.get("json")], sort_keys=True, default=str)


def _retry_after(response: requests.Response) -> float:
  try:
    requested = max(0.0, float(response.headers["Retry-After"]))
    return min(requested, config.NOTION_MAX_RETRY_AFTER)
  except (KeyError, ValueError):
    return config.NOTION_DEFAULT_RETRY_AFTER


def _request(method: str, path: str, **kwargs) -> dict:
  fresh = kwargs.pop("fresh", False)
  url = f"{config.NOTION_API}{path}"
  key = _cache_key(method, path, kwargs)

  cached = None if fresh else _cache.get(key)
  if cached is not None:
    budget.note_cache_hit()
    return cached

  for attempt in range(config.NOTION_MAX_RETRIES + 1):
    budget.charge_request()
    _limiter.acquire()
    response = requests.request(
      method,
      url,
      headers=config.notion_headers(),
      timeout=config.NOTION_TIMEOUT,
      **kwargs,
    )

    if response.status_code == 200:
      data = response.json()
      _cache.put(key, data)
      return data

    if response.status_code == 429:
      budget.note_rate_limited()
      if attempt < config.NOTION_MAX_RETRIES:
        time.sleep(_retry_after(response))
      continue

    raise requests.exceptions.HTTPError(
      f"API request failed with status {response.status_code}. Response: {response.text}",
      response=response)

  raise NotionRateLimitError(
    f"Notion kept returning 429 after {config.NOTION_MAX_RETRIES} retries for {method} {path}")


def _paginate(
  method: str,
  path: str,
  payload: dict | None = None,
  limit: int | None = None,
  fresh: bool = False,
  stop_when: Callable[[dict], bool] | None = None,
) -> NotionResults:
  results: list[dict] = []
  cursor = None
  bypass = {"fresh": True} if fresh else {}

  while True:
    body = dict(payload or {})
    if cursor:
      body["start_cursor"] = cursor
    if limit is not None:
      body["page_size"] = max(1, min(limit - len(results), 100))

    try:
      if method == "GET":
        data = _request(method, path, params=body, **bypass)
      else:
        data = _request(method, path, json=body, **bypass)
    except NotionRateLimitError:
      return NotionResults(results, partial=True, has_more=True, reason=RATE_LIMIT)
    except budget.BudgetExceeded:
      return NotionResults(results, partial=True, has_more=True, reason=BUDGET)

    batch = data.get("results", [])
    if stop_when:
      cut = next((i for i, item in enumerate(batch) if stop_when(item)), None)
      if cut is not None:
        results.extend(batch[:cut])
        return NotionResults(results)
    results.extend(batch)
    more_available = data.get("has_more", False)

    if limit is not None and len(results) >= limit:
      return NotionResults(results[:limit], has_more=more_available or len(results) > limit)

    if not more_available:
      return NotionResults(results)
    cursor = data.get("next_cursor")


def query_data_source(
  data_source_id: str, filters: dict | None = None, limit: int | None = None
) -> NotionResults:
  payload = {"filter": filters} if filters else {}
  return _paginate("POST", f"/data_sources/{data_source_id}/query", payload, limit)


def get_page(page_id: str, fresh: bool = False) -> dict:
  return _request("GET", f"/pages/{page_id}", **({"fresh": True} if fresh else {}))


def get_page_blocks(page_id: str, fresh: bool = False) -> NotionResults:
  return _paginate("GET", f"/blocks/{page_id}/children", fresh=fresh)


def search_edited_since(since: str | None = None) -> NotionResults:
  payload = {
    "filter": {"property": "object", "value": "page"},
    "sort": {"direction": "descending", "timestamp": "last_edited_time"},
  }
  stop_when = (lambda item: item.get("last_edited_time", "") < since) if since else None
  return _paginate("POST", "/search", payload, fresh=True, stop_when=stop_when)


def blocks_to_text(blocks: list[dict]) -> str:
  lines = []
  for block in blocks:
    block_type = block.get("type")
    rich_text = block.get(block_type, {}).get("rich_text", [])
    text = "".join(fragment.get("plain_text", "") for fragment in rich_text)
    if text:
      lines.append(text)
  return "\n".join(lines)


def search(query: str, filters: dict | None = None, limit: int | None = None) -> NotionResults:
  payload = {"query": query}
  if filters:
    payload["filter"] = filters
  return _paginate("POST", "/search", payload, limit)
