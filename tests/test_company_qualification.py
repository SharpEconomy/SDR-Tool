from __future__ import annotations

import json
from types import SimpleNamespace

from hackindia_leads.models import Event, Sponsor
from hackindia_leads.services.company_qualification import GeminiCompanyQualifier
from hackindia_leads.services.search import SearchResult


def _build_event() -> Event:
    return Event(
        source="ethglobal",
        url="https://ethglobal.com/events/demo",
        title="Demo Event",
        summary="AI builders event",
    )


def _fake_gemini_response(**overrides) -> dict[str, object]:
    payload = {
        "company_segment": "AI",
        "recently_funded": True,
        "recent_funding_signal": "Raised Series A in 2025",
        "company_location": "San Francisco, US",
        "location_priority": "US",
        "developer_adoption_need": True,
        "market_visibility_need": True,
        "qualification_notes": "Needs developer awareness.",
        "score": 88,
        "accepted": True,
    }
    payload.update(overrides)
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(payload),
                        }
                    ]
                }
            }
        ]
    }


def _install_fake_post(monkeypatch, response_payload: dict[str, object]) -> dict:
    captured: dict[str, object] = {"calls": 0}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return response_payload

    def fake_post(url, params, json, timeout):
        captured["calls"] += 1
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "hackindia_leads.services.company_qualification.requests.post",
        fake_post,
    )
    return captured


def test_gemini_company_qualifier_returns_none_without_api_key(settings) -> None:
    qualifier = GeminiCompanyQualifier(settings)

    result = qualifier.qualify(
        Sponsor(name="Example"),
        Event(source="ethglobal", url="https://example.com", title="Event"),
        "https://example.com",
        "example.com",
    )

    assert result is None


def test_gemini_company_qualifier_returns_none_when_disabled(settings) -> None:
    settings.gemini_api_key = "test-key"
    settings.gemini_enabled = False
    qualifier = GeminiCompanyQualifier(settings)

    result = qualifier.qualify(
        Sponsor(name="Example"),
        Event(source="ethglobal", url="https://example.com", title="Event"),
        "https://example.com",
        "example.com",
    )

    assert result is None


def test_gemini_company_qualifier_maps_response_payload(settings, monkeypatch) -> None:
    settings.gemini_api_key = "test-key"
    search_client = SimpleNamespace(
        search=lambda query, max_results: [
            SearchResult(
                "Funding",
                "https://news.example/funding",
                "Raised Series A",
            )
        ]
    )
    qualifier = GeminiCompanyQualifier(settings, search_client)
    captured = _install_fake_post(monkeypatch, _fake_gemini_response())

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
    assert captured["params"] == {"key": "test-key"}
    assert captured["timeout"] == settings.request_timeout_seconds
    prompt = captured["json"]["contents"][0]["parts"][0]["text"]
    assert "Example AI" in prompt
    assert "https://news.example/funding" in prompt


def test_gemini_company_qualifier_caches_by_company_and_domain(
    settings, monkeypatch
) -> None:
    settings.gemini_api_key = "test-key"
    qualifier = GeminiCompanyQualifier(
        settings,
        SimpleNamespace(search=lambda query, max_results: []),
    )
    captured = _install_fake_post(monkeypatch, _fake_gemini_response())

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
    assert captured["calls"] == 1
    assert captured["params"] == {"key": "test-key"}
