from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

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


def test_search_client_uses_google_custom_search_when_configured(settings) -> None:
    settings.google_search_api_key = "google-key"
    settings.google_search_engine_id = "engine-id"

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "items": [
                    {
                        "title": "Funding result",
                        "link": "https://example.com/funding",
                        "snippet": "Raised Series A",
                    }
                ]
            }

    captured = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    client = SearchClient(settings, session=SimpleNamespace(get=fake_get))

    results = client.search("example funding", max_results=3)

    assert [item.url for item in results] == ["https://example.com/funding"]
    assert captured["params"]["key"] == "google-key"
    assert captured["params"]["cx"] == "engine-id"
    assert captured["params"]["num"] == 3


def test_search_client_falls_back_to_ddgs_when_google_errors(
    settings, monkeypatch
) -> None:
    settings.google_search_api_key = "google-key"
    settings.google_search_engine_id = "engine-id"
    recent_date = (date.today() - timedelta(days=15)).strftime("%b %d, %Y")
    monkeypatch.setattr(
        search_module,
        "DDGS",
        lambda: FakeDDGS(
            [
                {
                    "title": f"Fallback result {recent_date}",
                    "href": "https://example.com/fallback",
                    "body": "Body text",
                }
            ]
        ),
    )

    def fake_get(url, params, timeout):
        raise RuntimeError("google failed")

    client = SearchClient(settings, session=SimpleNamespace(get=fake_get))

    results = client.search("example funding", max_results=3, recent_months=6)

    assert [item.url for item in results] == ["https://example.com/fallback"]


def test_search_client_filters_to_recent_dated_results(monkeypatch) -> None:
    recent_date = (date.today() - timedelta(days=20)).strftime("%b %d, %Y")
    stale_date = (date.today() - timedelta(days=260)).strftime("%b %d, %Y")
    monkeypatch.setattr(
        search_module,
        "DDGS",
        lambda: FakeDDGS(
            [
                {
                    "title": f"Recent funding {recent_date}",
                    "href": "https://example.com/recent",
                    "body": "Raised a round recently.",
                },
                {
                    "title": f"Old funding {stale_date}",
                    "href": "https://example.com/old",
                    "body": "Raised a round last year.",
                },
            ]
        ),
    )

    results = SearchClient().search("query", recent_months=6)

    assert [item.url for item in results] == ["https://example.com/recent"]
