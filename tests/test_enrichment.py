from __future__ import annotations

from hackindia_leads.models import Sponsor
from hackindia_leads.services.enrichment import ContactEnricher
from hackindia_leads.services.fetcher import FetchResult
from hackindia_leads.services.search import SearchResult


def test_resolve_website_prefers_valid_sponsor_website(settings, monkeypatch) -> None:
    enricher = ContactEnricher(settings)
    monkeypatch.setattr(enricher, "validate_website", lambda website: True)

    website = enricher.resolve_website(
        Sponsor(name="ENS", website="https://ens.domains/about")
    )

    assert website == "https://ens.domains"


def test_resolve_website_uses_search_fallback(settings, monkeypatch) -> None:
    enricher = ContactEnricher(settings)
    monkeypatch.setattr(
        enricher.search_client,
        "search",
        lambda query, max_results: [
            SearchResult("LinkedIn", "https://linkedin.com/company/test", ""),
            SearchResult("Official", "https://company.example/about", ""),
        ],
    )
    monkeypatch.setattr(enricher, "validate_website", lambda website: True)

    website = enricher.resolve_website(Sponsor(name="Example"))

    assert website == "https://company.example"


def test_validate_website_accepts_live_statuses(settings, monkeypatch) -> None:
    enricher = ContactEnricher(settings)
    monkeypatch.setattr(
        enricher.fetcher,
        "fetch",
        lambda url: FetchResult(
            url=url,
            status_code=403,
            text="blocked",
            used_browser=False,
        ),
    )

    assert enricher.validate_website("https://example.com") is True


def test_find_contact_candidates_combines_website_and_search(
    settings, monkeypatch
) -> None:
    enricher = ContactEnricher(settings)
    monkeypatch.setattr(
        enricher.fetcher,
        "fetch",
        lambda url: FetchResult(
            url=url,
            status_code=200,
            text="<html><body>Reach jane@example.com</body></html>",
            used_browser=False,
        ),
    )
    monkeypatch.setattr(
        enricher.search_client,
        "search",
        lambda query, max_results: [
            SearchResult(
                "Jane Doe - Head of Partnerships - Example | LinkedIn",
                "https://www.linkedin.com/in/jane-doe/",
                "",
            )
        ],
    )

    candidates = enricher.find_contact_candidates(
        Sponsor(name="Example"),
        "https://example.com",
        "example.com",
    )

    emails = [candidate.email for candidate in candidates]

    assert "jane@example.com" in emails
    assert "jane.doe@example.com" in emails
    assert candidates[0].email == "jane@example.com"


def test_title_score_and_bad_domain(settings) -> None:
    enricher = ContactEnricher(settings)

    assert enricher._title_score("VP Partnerships") > 0
    assert enricher._is_bad_domain("linkedin.com") is True
    assert enricher._is_bad_domain("example.com") is False
