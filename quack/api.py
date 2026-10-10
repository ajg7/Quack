import json
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from quack import config, streaming
from quack.retrieval import indexer
from quack.retrieval.store import IndexUnavailable, get_store
from quack.sessions import SessionStore
from quack.tools.notion import list_data_sources

app = FastAPI(title="Quack")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

sessions = SessionStore()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    model: str = config.MODEL

    @field_validator("model")
    @classmethod
    def model_is_known(cls, value: str) -> str:
        if value not in config.MODELS:
            raise ValueError(f"unknown model {value!r}")
        return value


def format_sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.MODEL}


@app.get("/models")
def models() -> dict:
    return {
        "default": config.MODEL,
        "models": [{"id": model_id, "label": label} for model_id, label in config.MODELS.items()],
    }


@app.get("/sources")
def sources() -> dict:
    try:
        return list_data_sources()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}"[:300]) from e


@app.get("/index")
def index_status() -> dict:
    try:
        stats = get_store().stats()
    except IndexUnavailable:
        return {"available": False, "chunks": 0, "pages": 0, "checkpoint": None}
    return {"available": True, **stats, "checkpoint": indexer.load_checkpoint()}


@app.post("/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    if not sessions.try_begin_turn(request.session_id):
        raise HTTPException(status_code=409, detail="The previous question is still being answered.")
    history = sessions.get(request.session_id)

    def generate() -> Iterator[str]:
        try:
            for event in streaming.stream_events(request.message, history, request.model):
                if event["event"] == "done":
                    sessions.append_turn(request.session_id, request.message, event["data"]["answer"])
                yield format_sse(event)
        finally:
            sessions.end_turn(request.session_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/sessions/{session_id}")
def clear_session(session_id: str) -> dict:
    return {"cleared": sessions.clear(session_id)}
