import contextlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from quack import config


class IndexUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Hit:
    page_id: str
    title: str
    url: str
    last_edited_time: str
    text: str
    distance: float


class ChromaStore:
    def __init__(
        self,
        path: Path | None = None,
        collection_name: str | None = None,
        embedding_function=None,
    ) -> None:
        self._embedding_function = embedding_function
        self._path = path or config.CHROMA_DIR
        self._collection_name = collection_name or config.INDEX_COLLECTION
        self._client = None
        self._lock = threading.RLock()

    def _collection(self):
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as e:
            raise IndexUnavailable("chromadb is not installed") from e

        if self._client is None:
            self._path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self._path), settings=Settings(anonymized_telemetry=False)
            )
        extra = {"embedding_function": self._embedding_function} if self._embedding_function else {}
        return self._client.get_or_create_collection(
            self._collection_name, metadata={"hnsw:space": "cosine"}, **extra
        )

    @contextlib.contextmanager
    def _guard(self) -> Iterator[None]:
        try:
            yield
        except IndexUnavailable:
            self._client = None
            raise
        except Exception as e:
            self._client = None
            raise IndexUnavailable(f"{type(e).__name__}: {e}") from e

    def replace_page(
        self, page_id: str, title: str, url: str, last_edited_time: str, chunks: list[str]
    ) -> int:
        with self._lock, self._guard():
            collection = self._collection()
            collection.delete(where={"page_id": page_id})
            if not chunks:
                return 0
            collection.upsert(
                ids=[f"{page_id}:{i}" for i in range(len(chunks))],
                documents=[f"{title}\n{chunk}" for chunk in chunks],
                metadatas=[
                    {
                        "page_id": page_id,
                        "title": title,
                        "url": url or "",
                        "last_edited_time": last_edited_time,
                        "chunk_index": i,
                    }
                    for i in range(len(chunks))
                ],
            )
            return len(chunks)

    def delete_page(self, page_id: str) -> None:
        with self._lock, self._guard():
            self._collection().delete(where={"page_id": page_id})

    def page_edited_time(self, page_id: str) -> str | None:
        with self._lock, self._guard():
            found = self._collection().get(where={"page_id": page_id}, limit=1, include=["metadatas"])
            metadatas = found.get("metadatas") or []
            return metadatas[0]["last_edited_time"] if metadatas else None

    def query(self, text: str, limit: int, page_id: str | None = None) -> list[Hit]:
        with self._lock, self._guard():
            collection = self._collection()
            total = collection.count()
            if total == 0:
                return []
            found = collection.query(
                query_texts=[text],
                n_results=min(limit, total),
                where={"page_id": page_id} if page_id else None,
                include=["documents", "metadatas", "distances"],
            )
            hits = []
            for document, meta, distance in zip(
                found["documents"][0], found["metadatas"][0], found["distances"][0]
            ):
                hits.append(
                    Hit(
                        page_id=meta["page_id"],
                        title=meta["title"],
                        url=meta["url"],
                        last_edited_time=meta["last_edited_time"],
                        text=document,
                        distance=distance,
                    )
                )
            return hits

    def stats(self) -> dict:
        with self._lock, self._guard():
            collection = self._collection()
            metadatas = collection.get(include=["metadatas"]).get("metadatas") or []
            return {
                "chunks": collection.count(),
                "pages": len({meta["page_id"] for meta in metadatas}),
            }


_default_store: ChromaStore | None = None
_default_lock = threading.Lock()


def get_store() -> ChromaStore:
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = ChromaStore()
        return _default_store
