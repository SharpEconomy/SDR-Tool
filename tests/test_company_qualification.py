from __future__ import annotations

from types import SimpleNamespace

from hackindia_leads.models import Event, Sponsor
from hackindia_leads.services.company_qualification import CompanyQualifier
from hackindia_leads.services.search import SearchResult


def _build_event() -> Event:
    return Event(
        source="ethglobal",
        url="https://ethglobal.com/events/demo",
        title="Demo Event",
        summary="AI builders event",
    )


def _search_results_for_query(query: str) -> list[SearchResult]:
    lowered = query.lower()
    if "raised funding" in lowered or "series" in lowered or "seed" in lowered:
        return [
            SearchResult(
                "Example AI raises Series A in 2025",
                "https://news.example/funding",
                "The startup raised Series A funding in 2025 for its AI platform.",
            )
        ]
    if "headquarters" in lowered or "based in" in lowered:
        return [
            SearchResult(
                "Example AI headquarters",
                "https://example.ai/about",
                "Example AI is based in San Francisco, United States.",
            )
        ]
    if "api sdk developers docs ecosystem" in lowered:
        return [
            SearchResult(
                "Developer platform",
                "https://example.ai/developers",
                "APIs, SDKs, docs, integrations, and a growing developer ecosystem.",
            )
        ]
    return [
        SearchResult(
            "Example AI launch and partnerships",
            "https://news.example/launch",
            "The company launched a new platform and expanded community partnerships.",
        )
    ]


def test_company_qualifier_returns_none_when_disabled(settings) -> None:
    settings.qualification_enabled = False
    qualifier = CompanyQualifier(settings)

    result = qualifier.qualify(
        Sponsor(name="Example"),
        Event(source="ethglobal", url="https://example.com", title="Event"),
        "https://example.com",
        "example.com",
    )

    assert result is None


def test_company_qualifier_scores_search_signals(settings) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results: _search_results_for_query(query)
    )
    qualifier = CompanyQualifier(settings, search_client)

    result = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )

    assert result is not None
    assert result.accepted is True
    assert result.company_segment == "AI"
    assert result.location_priority == "US"
    assert result.recently_funded is True
    assert result.developer_adoption_need is True
    assert result.market_visibility_need is True
    assert "Series A" in (result.recent_funding_signal or "")


def test_company_qualifier_caches_by_company_and_domain(settings) -> None:
    search_calls = {"count": 0}

    def fake_search(query, max_results):
        search_calls["count"] += 1
        return _search_results_for_query(query)

    qualifier = CompanyQualifier(
        settings,
        SimpleNamespace(search=fake_search),
    )

    first = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )
    second = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai/about"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )

    assert first is not None
    assert second is not None
    assert first == second
    assert search_calls["count"] == 4
