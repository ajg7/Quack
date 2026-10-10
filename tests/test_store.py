import hashlib

import pytest
from chromadb import EmbeddingFunction

from quack.retrieval.chunker import chunk_text
from quack.retrieval.store import ChromaStore, IndexUnavailable

VOCAB = ["tense", "latin", "ritual", "pray", "odyssey", "task", "fencing", "grammar"]


class WordEmbedding(EmbeddingFunction):
    def __init__(self):
        pass

    def __call__(self, input):
        vectors = []
        for text in input:
            lowered = text.lower()
            vector = [float(lowered.count(word)) for word in VOCAB]
            vector.append(0.01 + int(hashlib.md5(lowered.encode()).hexdigest()[:4], 16) / 1e6)
            vectors.append(vector)
        return vectors

    @staticmethod
    def name():
        return "quack-test-word-embedding"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return WordEmbedding()


@pytest.fixture
def store(tmp_path):
    return ChromaStore(tmp_path / "chroma", "test_pages", embedding_function=WordEmbedding())


def test_chunker_keeps_short_text_whole():
    assert chunk_text("one\n\ntwo") == ["one\ntwo"]


def test_chunker_splits_on_line_boundaries_under_the_limit():
    text = "\n".join(["a" * 40] * 5)

    chunks = chunk_text(text, max_chars=100, overlap=10)

    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "a" * 200


def test_chunker_hard_splits_a_long_line_with_overlap():
    chunks = chunk_text("x" * 250, max_chars=100, overlap=20)

    assert [len(c) for c in chunks] == [100, 100, 90, 10]


def test_chunker_returns_nothing_for_blank_text():
    assert chunk_text("  \n\n ") == []


def test_chunker_rejects_overlap_not_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=10, overlap=10)


def test_replace_then_query_returns_the_best_page_first(store):
    store.replace_page("p1", "Latin notes", "u1", "2026-01-01", ["tense tense latin grammar"])
    store.replace_page("p2", "Fencing", "u2", "2026-01-02", ["fencing fencing"])

    hits = store.query("sequence of tense", 2)

    assert hits[0].page_id == "p1"
    assert hits[0].title == "Latin notes"
    assert hits[0].last_edited_time == "2026-01-01"
    assert hits[0].text.startswith("Latin notes\n")


def test_replace_removes_the_pages_old_chunks(store):
    store.replace_page("p1", "T", "u", "t1", ["pray pray", "ritual", "task"])
    store.replace_page("p1", "T", "u", "t2", ["odyssey"])

    assert store.stats() == {"chunks": 1, "pages": 1}
    assert store.page_edited_time("p1") == "t2"


def test_page_edited_time_is_none_for_unknown_pages(store):
    assert store.page_edited_time("nope") is None


def test_delete_page_removes_all_chunks(store):
    store.replace_page("p1", "T", "u", "t", ["pray", "ritual"])
    store.delete_page("p1")

    assert store.stats()["chunks"] == 0


def test_query_can_be_restricted_to_one_page(store):
    store.replace_page("p1", "A", "u", "t", ["latin"])
    store.replace_page("p2", "B", "u", "t", ["latin"])

    hits = store.query("latin", 5, page_id="p2")

    assert {h.page_id for h in hits} == {"p2"}


def test_query_on_an_empty_index_returns_nothing(store):
    assert store.query("anything", 3) == []


def test_unavailable_when_the_backing_directory_is_a_file(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    broken = ChromaStore(blocker, "x", embedding_function=WordEmbedding())

    with pytest.raises(IndexUnavailable):
        broken.query("q", 1)


def test_backend_errors_become_index_unavailable_and_the_client_is_rebuilt(tmp_path, monkeypatch):
    store = ChromaStore(tmp_path / "chroma", "test_pages", embedding_function=WordEmbedding())
    store.replace_page("p1", "T", "u", "t", ["pray"])
    real = store._collection
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real()

    monkeypatch.setattr(store, "_collection", flaky)

    with pytest.raises(IndexUnavailable, match="database is locked"):
        store.query("pray", 1)

    assert store._client is None
    assert store.query("pray", 1)[0].page_id == "p1"
