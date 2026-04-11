from __future__ import annotations

from datetime import UTC, datetime

from growth_engine.discovery.adapters import (
    UserUrlDiscoveryAdapter,
    build_discovery_adapters,
)
from growth_engine.intake import BusinessProfileBuilder
from growth_engine.models import SearchResult
from growth_engine.services.fetcher import FetchResult
from growth_engine.services.search import SearchClient


class _DummyFetcher:
    def fetch(self, url, prefer_browser=False):
        return FetchResult(
            url=url,
            status_code=200,
            text="<html><title>Demo</title></html>",
            used_browser=False,
        )


class _DummySearchClient(SearchClient):
    def __init__(self, results):
        self.results = results

    def search(self, query: str, max_results: int = 5):
        return self.results[:max_results]


def test_user_url_adapter_fetches_seed_urls(settings, intake) -> None:
    profile = BusinessProfileBuilder().build(intake)
    adapter = UserUrlDiscoveryAdapter(settings, _DummyFetcher())

    documents = adapter.discover(profile, "customers")

    assert len(documents) == 1
    assert documents[0].source_type == "user_url"
    assert documents[0].url == "https://example.com/opportunity"


def test_build_discovery_adapters_includes_required_sources(settings) -> None:
    adapters = build_discovery_adapters(
        settings,
        _DummyFetcher(),
        _DummySearchClient(
            [
                SearchResult(
                    title="Retail buyer",
                    url="https://demo.example",
                    snippet="Retail distribution India",
                    published_at=datetime.now(UTC),
                )
            ]
        ),
    )

    assert {adapter.name for adapter in adapters} == {
        "user_urls",
        "public_web",
        "directories",
        "company_sites",
        "procurement",
    }
