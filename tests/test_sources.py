from __future__ import annotations

from types import SimpleNamespace

from hackindia_leads.services.fetcher import FetchResult
from hackindia_leads.services.search import SearchResult
from hackindia_leads.sources.base import SearchBackedSource, SourceAdapter
from hackindia_leads.sources.custom import CustomWebsiteSource
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


def test_parse_event_ignores_prize_labels_and_uses_logo_alt_text() -> None:
    html = """
    <html>
      <head><title>Prize Event</title></head>
      <body>
        <article>
          <h2>Hackathon Sponsors</h2>
          <a href="https://www.impetus.com">
            <img alt="Impetus" src="/impetus.png" />
          </a>
          <a href="https://aws.amazon.com/">
            <img alt="Amazon Web Services" src="/aws.png" />
          </a>
        </article>
        <div class="prize">
          <h3>1st Prize</h3>
          <div>$ 10,000 in cash</div>
          <div>1 winner</div>
        </div>
      </body>
    </html>
    """
    source = DummySource(SimpleNamespace(), SimpleNamespace())

    event = source.parse_event("https://events.example/1", html)

    assert event is not None
    assert [s.name for s in event.sponsors] == ["Impetus", "Amazon Web Services"]


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


def test_custom_source_normalizes_and_dedupes_urls() -> None:
    fetcher = SimpleNamespace(
        fetch=lambda url, prefer_browser=False: FetchResult(
            url=url,
            status_code=200,
            text="",
            used_browser=prefer_browser,
        )
    )
    source = CustomWebsiteSource(
        fetcher,
        SimpleNamespace(),
        [
            "demo.example/event",
            "https://demo.example/event",
            "https://two.example/hackathon?x=1",
        ],
    )

    urls = source.discover_event_urls([], 10)

    assert urls == [
        "https://demo.example/event",
        "https://two.example/hackathon?x=1",
    ]


def test_custom_source_discovers_event_pages_from_homepage() -> None:
    html_by_url = {
        "https://demo.example": '<a href="/hackathons">Hackathons</a>',
        "https://demo.example/hackathons": (
            '<a href="/2026/ai-hackathon">AI Hackathon</a>'
            '<a href="/contact">Contact</a>'
        ),
        "https://demo.example/events": "",
        "https://demo.example/challenges": "",
        "https://demo.example/buildathons": "",
        "https://demo.example/schedule": "",
    }
    fetcher = SimpleNamespace(
        fetch=lambda url, prefer_browser=False: FetchResult(
            url=url,
            status_code=200,
            text=html_by_url.get(url, ""),
            used_browser=prefer_browser,
        )
    )
    source = CustomWebsiteSource(fetcher, SimpleNamespace(), ["https://demo.example"])

    urls = source.discover_event_urls([], 5)

    assert urls == ["https://demo.example/2026/ai-hackathon"]


def test_custom_source_uses_openai_fallback_when_generic_parsing_finds_no_sponsors(
    settings,
) -> None:
    class FakeOpenAIClient:
        def is_configured(self) -> bool:
            return True

        def extract_sponsors(self, payload):
            return [
                {
                    "name": "OpenAI",
                    "website": "https://openai.com",
                    "evidence": "hackathon sponsors",
                },
                {
                    "name": "Stripe",
                    "website": "https://stripe.com",
                    "evidence": "partners",
                },
            ]

    fetcher = SimpleNamespace(settings=settings)
    source = CustomWebsiteSource(fetcher, SimpleNamespace(), [], FakeOpenAIClient())
    html = """
    <html>
      <head><title>Demo Hackathon</title></head>
      <body>
        <section>
          <h2>Ready to Partner with Us</h2>
          <a href="/contact">Partner with Demo</a>
        </section>
      </body>
    </html>
    """

    event = source.parse_event("https://demo.example/2026/demo-hackathon", html)

    assert event is not None
    assert [s.name for s in event.sponsors] == ["OpenAI", "Stripe"]


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


def test_devpost_accepts_only_event_subdomains() -> None:
    source = DevpostSource(SimpleNamespace(), SimpleNamespace())

    assert source.accepts_event_url("https://hack4ai.devpost.com/") is True
    assert source.accepts_event_url("https://devpost.com/hackathons") is False
    assert source.accepts_event_url("https://info.devpost.com/blog/x") is False


def test_dorahacks_accepts_event_detail_pages_only() -> None:
    source = DoraHacksSource(SimpleNamespace(), SimpleNamespace())

    assert (
        source.accepts_event_url("https://dorahacks.io/hackathon/p4w3/detail") is True
    )
    assert (
        source.accepts_event_url(
            "https://dorahacks.io/hackathon/origintrail-scaling-trust-ai"
        )
        is True
    )
    assert source.accepts_event_url("https://dorahacks.io/hackathon") is False
    assert source.accepts_event_url("https://dorahacks.io/") is False


def test_mlh_discover_event_urls_merges_listing_and_search() -> None:
    fetched_urls = []

    fetcher = SimpleNamespace(
        fetch=lambda url: (
            fetched_urls.append(url)
            or FetchResult(
                url=url,
                status_code=200,
                text=(
                    '<a href="https://events.mlh.io/events/1">One</a>'
                    '<a href="https://events.mlh.io/events/1">One Dup</a>'
                ),
                used_browser=False,
            )
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
    assert any("/seasons/" in url for url in fetched_urls)


def test_build_sources_returns_expected_keys(settings) -> None:
    sources = build_sources(SimpleNamespace(), SimpleNamespace())

    assert set(sources.keys()) == {"ethglobal", "devpost", "dorahacks", "mlh"}


def test_build_sources_includes_custom_when_urls_are_present(settings) -> None:
    sources = build_sources(
        SimpleNamespace(),
        SimpleNamespace(),
        ["demo.example/event"],
    )

    assert "custom" in sources
