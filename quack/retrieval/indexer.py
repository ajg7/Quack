import json
import time
from dataclasses import dataclass, field

from quack import budget, config, tracing
from quack.integrations import notion
from quack.retrieval.chunker import chunk_text
from quack.retrieval.store import IndexUnavailable, get_store
from quack.tools.notion import object_title

CHECKPOINT_FILE = "checkpoint.json"


class IncompletePage(RuntimeError):
    def __init__(self, page_id: str, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Could not read all of page {page_id} ({reason})")


@dataclass
class IndexedPage:
    page_id: str
    title: str
    last_edited_time: str
    chunks: int
    text: str


@dataclass
class IndexReport:
    request_id: str
    pages_found: int = 0
    pages_indexed: int = 0
    pages_skipped: int = 0
    chunks_upserted: int = 0
    notion_requests: int = 0
    checkpoint: str | None = None
    complete: bool = True
    errors: list[str] = field(default_factory=list)
    latency_ms: int = 0


def load_checkpoint() -> str | None:
    try:
        with open(config.CHROMA_DIR / CHECKPOINT_FILE, encoding="utf-8") as f:
            return json.load(f).get("last_edited_time")
    except (OSError, ValueError):
        return None


def save_checkpoint(last_edited_time: str) -> None:
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.CHROMA_DIR / CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_edited_time": last_edited_time}, f)


def index_page(page: dict, store) -> IndexedPage:
    page_id = page["id"]
    blocks = notion.get_page_blocks(page_id, fresh=True)
    if blocks.partial:
        raise IncompletePage(page_id, blocks.reason)

    title = object_title(page)
    text = notion.blocks_to_text(blocks.results)
    chunks = chunk_text(text) or [""]
    edited = page.get("last_edited_time", "")
    store.replace_page(page_id, title, page.get("url", ""), edited, chunks)
    return IndexedPage(page_id, title, edited, len(chunks), text)


def run(store=None, full: bool = False, limit: int | None = None) -> IndexReport:
    store = store or get_store()
    request_id = tracing.new_request_id()
    started = time.perf_counter()
    report = IndexReport(request_id)
    since = None if full else load_checkpoint()

    tracing.emit("index_start", request_id, full=full, since=since, limit=limit)

    run_budget = budget.Budget(
        max_requests=config.INDEX_MAX_REQUESTS,
        deadline_seconds=config.INDEX_DEADLINE_SECONDS,
    )
    with budget.activate(run_budget):
        try:
            found = notion.search_edited_since(since)
            report.pages_found = len(found.results)
            if found.partial:
                report.complete = False
                report.errors.append(f"Page listing was cut short ({found.reason})")

            pending = list(reversed(found.results))[:limit]
            if limit is not None and len(found.results) > limit:
                report.complete = False

            frozen = False
            for page in pending:
                edited = page.get("last_edited_time", "")
                try:
                    if store.page_edited_time(page["id"]) == edited:
                        report.pages_skipped += 1
                    else:
                        indexed = index_page(page, store)
                        report.pages_indexed += 1
                        report.chunks_upserted += indexed.chunks
                        tracing.emit(
                            "index_page",
                            request_id,
                            page_id=indexed.page_id,
                            chunks=indexed.chunks,
                            last_edited_time=edited,
                        )
                    if not frozen:
                        save_checkpoint(edited)
                        report.checkpoint = edited
                except IndexUnavailable:
                    raise
                except (budget.BudgetExceeded, IncompletePage) as e:
                    report.errors.append(f"{page.get('id')}: {e}")
                    report.complete = False
                    if isinstance(e, budget.BudgetExceeded) or e.reason == notion.BUDGET:
                        break
                    frozen = True
                except Exception as e:
                    frozen = True
                    report.complete = False
                    report.errors.append(f"{page.get('id')}: {type(e).__name__}: {e}")
        except IndexUnavailable as e:
            report.complete = False
            report.errors.append(f"Index unavailable: {e}")

    report.notion_requests = run_budget.requests
    report.latency_ms = round((time.perf_counter() - started) * 1000)
    tracing.emit(
        "index_end",
        request_id,
        pages_found=report.pages_found,
        pages_indexed=report.pages_indexed,
        pages_skipped=report.pages_skipped,
        chunks_upserted=report.chunks_upserted,
        notion_requests=report.notion_requests,
        complete=report.complete,
        errors=len(report.errors),
        latency_ms=report.latency_ms,
    )
    return report
