import pytest

from quack.retrieval.store import Hit, IndexUnavailable


class FakeStore:
    def __init__(self):
        self.pages = {}
        self.fail = None
        self.replaced = []
        self.deleted = []

    def _check(self):
        if self.fail:
            raise IndexUnavailable(self.fail)

    def replace_page(self, page_id, title, url, last_edited_time, chunks):
        self._check()
        self.pages[page_id] = {"title": title, "url": url, "edited": last_edited_time, "chunks": chunks}
        self.replaced.append(page_id)
        return len(chunks)

    def delete_page(self, page_id):
        self._check()
        self.pages.pop(page_id, None)
        self.deleted.append(page_id)

    def page_edited_time(self, page_id):
        self._check()
        page = self.pages.get(page_id)
        return page["edited"] if page else None

    def query(self, text, limit, page_id=None):
        self._check()
        words = set(text.lower().split())
        scored = []
        for pid, page in self.pages.items():
            if page_id and pid != page_id:
                continue
            for chunk in page["chunks"]:
                overlap = len(words & set(chunk.lower().split()))
                scored.append((-overlap, pid, page, chunk))
        scored.sort(key=lambda item: item[0])
        return [
            Hit(pid, page["title"], page["url"], page["edited"], f"{page['title']}\n{chunk}", 0.1 * i)
            for i, (_, pid, page, chunk) in enumerate(scored[:limit])
        ]

    def stats(self):
        self._check()
        return {"chunks": sum(len(p["chunks"]) for p in self.pages.values()), "pages": len(self.pages)}


@pytest.fixture
def fake_store():
    return FakeStore()
