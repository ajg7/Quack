import json
import uuid
from datetime import datetime, timezone

from quack import config

TRACE_FILE = "quack.jsonl"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def read_events(request_id: str) -> list[dict]:
    path = config.TRACE_DIR / TRACE_FILE
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("request_id") == request_id:
                events.append(record)
    return events


def emit(event: str, request_id: str, **fields) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "event": event,
        **fields,
    }
    try:
        config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.TRACE_DIR / TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except (OSError, TypeError, ValueError):
        pass
