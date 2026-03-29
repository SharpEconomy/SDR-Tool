from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from hackindia_leads.models import (
    CompanyQualification,
    ContactCandidate,
    EmailValidation,
    Event,
    Sponsor,
)
from hackindia_leads.services.company_qualification import CompanyQualifier
from hackindia_leads.services.search import SearchResult


def _build_event() -> Event:
    return Event(
        source="ethglobal",
        url="https://ethglobal.com/events/demo",
        title="Demo Event",
        summary="AI builders event",
    )


def _search_results_for_query(
    query: str, recent_months: int | None
) -> list[SearchResult]:
    lowered = query.lower()
    recent_date = date.today() - timedelta(days=25)
    stale_date = date.today() - timedelta(days=240)
    if "raised funding" in lowered or "series" in lowered or "seed" in lowered:
        return [
            SearchResult(
                title="Example AI raises Series A",
                url="https://news.example/funding",
                snippet="The startup raised Series A funding for its AI platform.",
                published_at=recent_date if recent_months is not None else stale_date,
            )
        ]
    if "headquarters" in lowered or "based in" in lowered:
        return [
            SearchResult(
                title="Example AI headquarters",
                url="https://example.ai/about",
                snippet="Example AI is based in San Francisco, United States.",
            )
        ]
    return [
        SearchResult(
            title="Developer platform",
            url="https://example.ai/developers",
            snippet=(
                "APIs, SDKs, docs, integrations, and a growing developer ecosystem."
            ),
        )
    ]


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.contact_calls: list[dict[str, object]] = []
        self.sponsor_calls: list[dict[str, object]] = []

    def is_configured(self) -> bool:
        return True

    def qualify(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        recent_evidence = payload.get("recent_evidence") or []
        if not recent_evidence:
            return {
                "accepted": False,
                "score": 12,
                "recently_funded": False,
                "recent_funding_signal": None,
                "market_visibility_need": False,
                "qualification_notes": "No sufficiently recent dated evidence.",
            }
        return {
            "accepted": True,
            "score": 84,
            "recently_funded": True,
            "recent_funding_signal": "Example AI raises Series A",
            "market_visibility_need": True,
            "qualification_notes": (
                "Recent funding and developer push support outreach."
            ),
        }

    def review_contacts(self, payload: dict[str, object]) -> dict[str, object]:
        self.contact_calls.append(payload)
        return {
            "contacts": [
                {
                    "email": "jane@example.ai",
                    "accepted": True,
                    "score": 92,
                    "reason": "Head of Partnerships matches the outreach goal.",
                },
                {
                    "email": "hello@example.ai",
                    "accepted": False,
                    "score": 21,
                    "reason": "Generic inbox is weaker than the named contact.",
                },
            ],
            "selection_notes": "Prioritize direct sponsorship owners.",
        }

    def extract_sponsors(self, payload: dict[str, object]) -> list[dict[str, object]]:
        self.sponsor_calls.append(payload)
        return [
            {
                "name": "OpenAI",
                "website": "https://openai.com",
                "evidence": "hackathon sponsors",
            }
        ]


class BrokenOpenAIClient(FakeOpenAIClient):
    def qualify(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        raise RuntimeError("openai unavailable")

    def review_contacts(self, payload: dict[str, object]) -> dict[str, object]:
        self.contact_calls.append(payload)
        raise RuntimeError("openai unavailable")


def _build_qualification() -> CompanyQualification:
    return CompanyQualification(
        company_segment="AI",
        recently_funded=True,
        recent_funding_signal="Example AI raises Series A",
        company_location="United States",
        location_priority="US",
        developer_adoption_need=True,
        market_visibility_need=True,
        qualification_notes="Recent funding and developer push support outreach.",
        score=84,
        accepted=True,
    )


def _build_contacts() -> tuple[list[ContactCandidate], dict[str, EmailValidation]]:
    contacts = [
        ContactCandidate(
            full_name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            title="Head of Partnerships",
            email="jane@example.ai",
            source="public-search-pattern",
            linkedin_url="https://linkedin.com/in/jane",
            confidence=90,
        ),
        ContactCandidate(
            full_name="Hello",
            first_name=None,
            last_name=None,
            title="Website contact",
            email="hello@example.ai",
            source="website-email",
            linkedin_url=None,
            confidence=35,
        ),
    ]
    validations = {
        "jane@example.ai": EmailValidation(True, True, 250, "ok"),
        "hello@example.ai": EmailValidation(True, True, 250, "ok"),
    }
    return contacts, validations


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


def test_company_qualifier_uses_openai_with_recent_evidence(settings) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
    )
    openai_client = FakeOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)

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
    assert openai_client.calls
    assert openai_client.calls[0]["rule_hints"]["company_segment"] == "AI"


def test_company_qualifier_falls_back_when_openai_is_not_configured(settings) -> None:
    settings.openai_api_key = ""
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
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
    assert "rule-based fallback used because OpenAI is unavailable" in (
        result.qualification_notes or ""
    )


def test_company_qualifier_falls_back_when_openai_is_disabled(settings) -> None:
    settings.use_openai_qualification = False
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
    )
    openai_client = FakeOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)

    result = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )

    assert result is not None
    assert result.accepted is True
    assert openai_client.calls == []
    assert "rule-based fallback used because OpenAI is disabled" in (
        result.qualification_notes or ""
    )


def test_company_qualifier_falls_back_when_openai_errors(settings) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
    )
    openai_client = BrokenOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)

    result = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )

    assert result is not None
    assert result.accepted is True
    assert len(openai_client.calls) == 1
    assert "rule-based fallback used after OpenAI error" in (
        result.qualification_notes or ""
    )


def test_company_qualifier_accepts_clear_company_when_recent_evidence_is_missing(
    settings,
) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: (
            []
            if recent_months is not None
            else _search_results_for_query(query, recent_months)
        )
    )
    openai_client = FakeOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)

    result = qualifier.qualify(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
    )

    assert result is not None
    assert result.accepted is True
    assert result.score == 60
    assert "No sufficiently recent dated evidence." in (
        result.qualification_notes or ""
    )
    assert "accepted by sponsor-domain fit override" in (
        result.qualification_notes or ""
    )
    assert len(openai_client.calls) == 1
    assert openai_client.calls[0]["recent_evidence"] == []


def test_company_qualifier_caches_by_company_and_domain(settings) -> None:
    search_calls = {"count": 0}

    def fake_search(query, max_results, recent_months=None):
        search_calls["count"] += 1
        return _search_results_for_query(query, recent_months)

    qualifier = CompanyQualifier(
        settings,
        SimpleNamespace(search=fake_search),
        FakeOpenAIClient(),
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
    assert search_calls["count"] == 3


def test_company_qualifier_reviews_contacts_with_openai(settings) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
    )
    openai_client = FakeOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)
    contacts, validations = _build_contacts()

    reviews = qualifier.review_contacts(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
        _build_qualification(),
        contacts,
        validations,
    )

    assert reviews["jane@example.ai"].accepted is True
    assert reviews["jane@example.ai"].score == 92
    assert "Prioritize direct sponsorship owners." in (
        reviews["jane@example.ai"].notes or ""
    )
    assert reviews["hello@example.ai"].accepted is False
    assert len(openai_client.contact_calls) == 1


def test_company_qualifier_reviews_contacts_with_fallback_when_openai_errors(
    settings,
) -> None:
    search_client = SimpleNamespace(
        search=lambda query, max_results, recent_months=None: _search_results_for_query(
            query,
            recent_months,
        )
    )
    openai_client = BrokenOpenAIClient()
    qualifier = CompanyQualifier(settings, search_client, openai_client)
    contacts, validations = _build_contacts()

    reviews = qualifier.review_contacts(
        Sponsor(name="Example AI", website="https://example.ai"),
        _build_event(),
        "https://example.ai",
        "example.ai",
        _build_qualification(),
        contacts,
        validations,
    )

    assert reviews["jane@example.ai"].accepted is True
    assert reviews["hello@example.ai"].accepted is True
    assert "rule-based contact fallback used after OpenAI error" in (
        reviews["jane@example.ai"].notes or ""
    )
    assert len(openai_client.contact_calls) == 1


def test_openai_client_extracts_sponsors_payload_shape(settings) -> None:
    client = FakeOpenAIClient()

    sponsors = client.extract_sponsors(
        {
            "event_url": "https://example.ai/hackathon",
            "page_title": "Example Hackathon",
            "headings": ["Hackathon Sponsors"],
            "links": [{"text": "OpenAI", "href": "https://openai.com"}],
            "body_excerpt": "OpenAI supports the event.",
        }
    )

    assert sponsors == [
        {
            "name": "OpenAI",
            "website": "https://openai.com",
            "evidence": "hackathon sponsors",
        }
    ]
