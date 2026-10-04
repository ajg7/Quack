import threading
import time
from dataclasses import dataclass, field

import requests

from quack import config


@dataclass
class NotionResults:
  results: list[dict] = field(default_factory=list)
  partial: bool = False


@dataclass
class NotionStats:
  requests: int = 0
  rate_limited: int = 0


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
stats = NotionStats()


def _retry_after(response: requests.Response) -> float:
  try:
    return max(0.0, float(response.headers["Retry-After"]))
  except (KeyError, ValueError):
    return config.NOTION_DEFAULT_RETRY_AFTER


def _request(method: str, path: str, **kwargs) -> dict:
  url = f"{config.NOTION_API}{path}"

  for attempt in range(config.NOTION_MAX_RETRIES + 1):
    _limiter.acquire()
    stats.requests += 1
    response = requests.request(
      method,
      url,
      headers=config.notion_headers(),
      timeout=config.NOTION_TIMEOUT,
      **kwargs,
    )

    if response.status_code == 200:
      return response.json()

    if response.status_code == 429:
      stats.rate_limited += 1
      if attempt < config.NOTION_MAX_RETRIES:
        time.sleep(_retry_after(response))
      continue

    raise requests.exceptions.HTTPError(
      f"API request failed with status {response.status_code}. Response: {response.text}",
      response=response)

  raise NotionRateLimitError(
    f"Notion kept returning 429 after {config.NOTION_MAX_RETRIES} retries for {method} {path}")


def _paginate(method: str, path: str, payload: dict | None = None) -> NotionResults:
  results: list[dict] = []
  cursor = None

  while True:
    body = dict(payload or {})
    if cursor:
      body["start_cursor"] = cursor

    try:
      if method == "GET":
        data = _request(method, path, params=body)
      else:
        data = _request(method, path, json=body)
    except NotionRateLimitError:
      return NotionResults(results, partial=True)

    results.extend(data.get("results", []))

    if not data.get("has_more", False):
      return NotionResults(results)
    cursor = data.get("next_cursor")


def query_data_source(data_source_id: str, filters: dict | None = None) -> NotionResults:
  payload = {"filter": filters} if filters else {}
  return _paginate("POST", f"/data_sources/{data_source_id}/query", payload)


def get_page_blocks(page_id: str) -> NotionResults:
  return _paginate("GET", f"/blocks/{page_id}/children")


def blocks_to_text(blocks: list[dict]) -> str:
  lines = []
  for block in blocks:
    block_type = block.get("type")
    rich_text = block.get(block_type, {}).get("rich_text", [])
    text = "".join(fragment.get("plain_text", "") for fragment in rich_text)
    if text:
      lines.append(text)
  return "\n".join(lines)


def search(query: str, filters: dict | None = None) -> NotionResults:
  payload = {"query": query}
  if filters:
    payload["filter"] = filters
  return _paginate("POST", "/search", payload)
