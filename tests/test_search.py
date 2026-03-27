from __future__ import annotations

from hackindia_leads.services import search as search_module
from hackindia_leads.services.search import SearchClient


class FakeDDGS:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, query, max_results):
        return self.rows


def test_search_client_maps_results(monkeypatch) -> None:
    monkeypatch.setattr(
        search_module,
        "DDGS",
        lambda: FakeDDGS(
            [
                {"title": "A", "href": "https://example.com", "body": "snippet"},
                {"title": "B", "url": "https://example.org", "body": "text"},
                {"title": "C", "body": "missing url"},
            ]
        ),
    )

    results = SearchClient().search("query")

    assert [item.url for item in results] == [
        "https://example.com",
        "https://example.org",
    ]


def test_search_client_returns_empty_on_failure(monkeypatch) -> None:
    class BrokenDDGS:
        def __enter__(self):
            raise RuntimeError("broken")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(search_module, "DDGS", lambda: BrokenDDGS())

    assert SearchClient().search("query") == []
