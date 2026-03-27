from __future__ import annotations

from types import SimpleNamespace

from hackindia_leads.services.fetcher import FetchResult
from hackindia_leads.services.search import SearchResult
from hackindia_leads.sources.base import SearchBackedSource, SourceAdapter
from hackindia_leads.sources.devpost import DevpostSource
from hackindia_leads.sources.dorahacks import DoraHacksSource
from hackindia_leads.sources.ethglobal import EthGlobalSource
from hackindia_leads.sources.mlh import MLHSource
from hackindia_leads.sources.registry import build_sources


class DummySource(SourceAdapter):
    @property
    def name(self) -> str:
        return "dummy"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        return ["https://events.example/1"]


class DummySearchSource(SearchBackedSource):
    domain = "example.com"
    query_format = 'site:example.com "{keyword}"'

    @property
    def name(self) -> str:
        return "dummy-search"


def test_parse_event_extracts_sponsors_from_section() -> None:
    html = """
    <html>
      <head>
        <title>Example Event</title>
        <meta name="description" content="This is an event about AI and Web3.">
      </head>
      <body>
        <section>
          <h2>Sponsors</h2>
          <a href="https://ens.domains">ENS</a>
          <a href="https://world.org">World</a>
        </section>
      </body>
    </html>
    """
    source = DummySource(SimpleNamespace(), SimpleNamespace())

    event = source.parse_event("https://events.example/1", html)

    assert event is not None
    assert event.title == "Example Event"
    assert [s.name for s in event.sponsors] == ["ENS", "World"]


def test_extract_sponsors_from_jsonish() -> None:
    source = DummySource(SimpleNamespace(), SimpleNamespace())
    html = (
        '\\"organization\\":{\\"id\\":1,\\"name\\":\\"ENS\\",'
        '\\"website\\":\\"https://ens.domains\\"}'
    )

    sponsors = source.extract_sponsors_from_jsonish(html)

    assert len(sponsors) == 1
    assert sponsors[0].website == "https://ens.domains"


def test_search_backed_source_filters_and_dedupes_urls() -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results: [
            SearchResult("A", "https://example.com/a", ""),
            SearchResult("A2", "https://example.com/a", ""),
            SearchResult("B", "https://other.com/b", ""),
        ]
    )
    source = DummySearchSource(SimpleNamespace(), search_client)

    urls = source.discover_event_urls(["ai"], 5)

    assert urls == ["https://example.com/a"]


def test_ethglobal_discover_event_urls_filters_blocked_tokens(settings) -> None:
    fetcher = SimpleNamespace(
        fetch=lambda url: FetchResult(
            url=url,
            status_code=200,
            text=(
                '<a href="/events/cannes2026">A</a>'
                '<a href="/events/pragma-cannes2026">B</a>'
                '<a href="/events/happy-hour-berlin">C</a>'
            ),
            used_browser=False,
        )
    )
    source = EthGlobalSource(fetcher, SimpleNamespace())

    urls = source.discover_event_urls(["ai"], 5)

    assert urls == ["https://ethglobal.com/events/cannes2026"]


def test_browser_flags_for_sources(settings) -> None:
    fetcher = SimpleNamespace()
    search_client = SimpleNamespace()

    assert DevpostSource(fetcher, search_client).should_use_browser("x") is True
    assert DoraHacksSource(fetcher, search_client).should_use_browser("x") is True
    assert MLHSource(fetcher, search_client).should_use_browser("x") is True


def test_mlh_discover_event_urls_merges_listing_and_search() -> None:
    fetcher = SimpleNamespace(
        fetch=lambda url: FetchResult(
            url=url,
            status_code=200,
            text=(
                '<a href="https://events.mlh.io/events/1">One</a>'
                '<a href="https://events.mlh.io/events/1">One Dup</a>'
            ),
            used_browser=False,
        )
    )
    search_client = SimpleNamespace(
        search=lambda query, max_results: [
            SearchResult("Two", "https://events.mlh.io/events/2", "")
        ]
    )
    source = MLHSource(fetcher, search_client)

    urls = source.discover_event_urls(["ai"], 5)

    assert urls == [
        "https://events.mlh.io/events/1",
        "https://events.mlh.io/events/2",
    ]


def test_build_sources_returns_expected_keys(settings) -> None:
    sources = build_sources(SimpleNamespace(), SimpleNamespace())

    assert set(sources.keys()) == {"ethglobal", "devpost", "dorahacks", "mlh"}
