from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace

import pandas as pd

from hackindia_leads.models import (
    PUBLIC_LEAD_COLUMNS,
    CompanyQualification,
    ContactCandidate,
    ContactReview,
    EmailValidation,
    Event,
    Sponsor,
)
from hackindia_leads.pipeline import LeadPipeline, PipelineControl, PipelineResult
from hackindia_leads.services.company_qualification import CompanyQualifier
from hackindia_leads.services.search import SearchResult


class _BrokenOpenAIClient:
    def is_configured(self) -> bool:
        return True

    def qualify(self, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("openai unavailable")

    def review_contacts(self, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("openai unavailable")


def _fallback_search_results(
    query: str, recent_months: int | None = None
) -> list[SearchResult]:
    lowered = query.lower()
    recent_date = date.today() - timedelta(days=25)
    if "raised funding" in lowered or "series" in lowered or "seed" in lowered:
        return [
            SearchResult(
                title="ENS raises Series A",
                url="https://news.example/ens-funding",
                snippet="ENS announced Series A funding and ecosystem expansion.",
                published_at=recent_date if recent_months is not None else None,
            )
        ]
    if "headquarters" in lowered or "based in" in lowered:
        return [
            SearchResult(
                title="ENS headquarters",
                url="https://ens.domains/about",
                snippet="ENS is based in New York, United States.",
                published_at=None,
            )
        ]
    return [
        SearchResult(
            title="ENS developer platform",
            url="https://ens.domains/developers",
            snippet=(
                "APIs, SDKs, docs, integrations, and a growing " "developer ecosystem."
            ),
            published_at=None,
        )
    ]


def _build_event(
    *,
    url: str = "https://ethglobal.com/events/mumbai",
    title: str = "ETHGlobal Mumbai",
    sponsors: list[Sponsor] | None = None,
) -> Event:
    return Event(
        source="ethglobal",
        url=url,
        title=title,
        sponsors=sponsors or [Sponsor(name="ENS", website="https://ens.domains")],
    )


def _build_contact(
    *,
    email: str = "jane@ens.domains",
    linkedin_url: str | None = "https://linkedin.com/in/jane",
) -> ContactCandidate:
    return ContactCandidate(
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        title="Head of Partnerships",
        email=email,
        source="public-search-pattern",
        linkedin_url=linkedin_url,
        confidence=90,
    )


def _build_validation(
    *,
    syntax_valid: bool = True,
    mx_valid: bool = True,
    smtp_code: int | None = 250,
    smtp_message: str | None = "ok",
) -> EmailValidation:
    return EmailValidation(
        syntax_valid=syntax_valid,
        mx_valid=mx_valid,
        smtp_code=smtp_code,
        smtp_message=smtp_message,
    )


def _stub_source_events(
    pipeline: LeadPipeline,
    events: list[Event],
    *,
    source_name: str = "ethglobal",
) -> None:
    pipeline.sources = {
        source_name: SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: events
        )
    }


def _stub_enrichment(
    pipeline: LeadPipeline,
    monkeypatch,
    *,
    website: str = "https://ens.domains",
    domain: str = "ens.domains",
    website_is_valid: bool = True,
    contacts: list[ContactCandidate] | None = None,
    validation: EmailValidation | None = None,
) -> None:
    monkeypatch.setattr(pipeline.enricher, "resolve_website", lambda sponsor: website)
    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_domain",
        lambda sponsor, resolved_website: domain,
    )
    monkeypatch.setattr(
        pipeline.enricher,
        "validate_website",
        lambda resolved_website: website_is_valid,
    )
    if contacts is not None:
        monkeypatch.setattr(
            pipeline.enricher,
            "find_contact_candidates",
            lambda sponsor, resolved_website, resolved_domain: contacts,
        )
    if validation is not None:
        monkeypatch.setattr(
            pipeline.validator,
            "validate",
            lambda email: validation,
        )


def test_pipeline_result_dataframe() -> None:
    result = PipelineResult(rows=[], export_name="empty.xlsx", export_bytes=b"")

    frame = result.dataframe()

    assert frame.empty
    assert frame.columns.tolist() == PUBLIC_LEAD_COLUMNS


def test_pipeline_run_writes_only_accepted_leads(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(
        pipeline,
        [
            _build_event(
                sponsors=[
                    Sponsor(
                        name="ENS",
                        website="https://ens.domains",
                        evidence="embedded-json",
                    )
                ]
            )
        ],
    )
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact()],
        validation=_build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert result.rows[0].decision_maker_email == "jane@ens.domains"
    assert result.export_name.startswith("hackindia_leads_")
    assert result.export_name.endswith(".xlsx")
    exported_frame = pd.read_excel(BytesIO(result.export_bytes))
    assert exported_frame.columns.tolist() == PUBLIC_LEAD_COLUMNS
    assert exported_frame.loc[0, "decision_maker_email"] == "jane@ens.domains"


def test_pipeline_run_dedupes_duplicate_sponsors(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    events = [
        _build_event(),
        _build_event(
            url="https://ethglobal.com/events/nyc",
            title="ETHGlobal NYC",
        ),
    ]
    _stub_source_events(pipeline, events)
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
        validation=_build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 2)

    assert len(result.rows) == 1
    assert result.rows[0].sponsor_company == "ENS"


def test_pipeline_run_keeps_multiple_contacts_per_sponsor(
    settings, monkeypatch
) -> None:
    settings.qualification_enabled = False
    settings.max_contacts_per_company = 2
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[
            _build_contact(email="first@ens.domains", linkedin_url=None),
            _build_contact(email="second@ens.domains", linkedin_url=None),
            _build_contact(email="third@ens.domains", linkedin_url=None),
        ],
    )
    monkeypatch.setattr(
        pipeline.validator,
        "validate",
        lambda email: _build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert [row.decision_maker_email for row in result.rows] == [
        "first@ens.domains",
        "second@ens.domains",
    ]


def test_pipeline_run_dedupes_duplicate_linkedin_urls(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    settings.max_contacts_per_company = 3
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[
            _build_contact(
                email="first@ens.domains",
                linkedin_url="https://linkedin.com/in/jane-doe/",
            ),
            _build_contact(
                email="second@ens.domains",
                linkedin_url="https://linkedin.com/in/jane-doe?trk=public_profile",
            ),
            _build_contact(
                email="third@ens.domains",
                linkedin_url="https://linkedin.com/in/john-doe",
            ),
        ],
    )
    monkeypatch.setattr(
        pipeline.validator,
        "validate",
        lambda email: _build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert [row.decision_maker_email for row in result.rows] == [
        "first@ens.domains",
        "third@ens.domains",
    ]


def test_pipeline_run_filters_sponsor_with_failed_fit_check(
    settings, monkeypatch
) -> None:
    pipeline = LeadPipeline(settings)
    _stub_source_events(
        pipeline,
        [
            _build_event(
                sponsors=[Sponsor(name="Example", website="https://example.com")]
            )
        ],
    )
    _stub_enrichment(
        pipeline,
        monkeypatch,
        website="https://example.com",
        domain="example.com",
        website_is_valid=True,
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "qualify",
        lambda sponsor, event, website, domain: CompanyQualification(
            company_segment="Other",
            recently_funded=False,
            recent_funding_signal="No funding found",
            company_location="Unknown",
            location_priority="Unknown",
            developer_adoption_need=False,
            market_visibility_need=False,
            qualification_notes="Not a fit.",
            score=12,
            accepted=False,
        ),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert result.rows == []


def test_pipeline_run_falls_back_when_openai_is_not_configured(
    settings, monkeypatch
) -> None:
    settings.openai_api_key = ""
    pipeline = LeadPipeline(settings)
    monkeypatch.setattr(
        pipeline.qualifier.search_client,
        "search",
        lambda query, max_results, recent_months=None: _fallback_search_results(
            query,
            recent_months,
        ),
    )
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
        validation=_build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert "rule-based fallback used because OpenAI is unavailable" in (
        result.rows[0].qualification_notes or ""
    )
    assert "rule-based contact fallback used because OpenAI is unavailable" in (
        result.rows[0].contact_review_notes or ""
    )


def test_pipeline_run_falls_back_when_openai_errors(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    pipeline.qualifier = CompanyQualifier(
        settings,
        SimpleNamespace(
            search=lambda query, max_results, recent_months=None: (
                _fallback_search_results(query, recent_months)
            )
        ),
        _BrokenOpenAIClient(),
    )
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
        validation=_build_validation(),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert "rule-based fallback used after OpenAI error" in (
        result.rows[0].qualification_notes or ""
    )
    assert "rule-based contact fallback used after OpenAI error" in (
        result.rows[0].contact_review_notes or ""
    )


def test_pipeline_run_skips_qualification_when_disabled(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
        validation=_build_validation(),
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "qualify",
        lambda sponsor, event, website, domain: (_ for _ in ()).throw(
            AssertionError("Qualification should be skipped when disabled")
        ),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert result.rows[0].qualification_accepted is True
    assert result.rows[0].company_segment is None


def test_pipeline_run_sorts_us_and_india_fit_first(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    events = [
        _build_event(
            url="https://ethglobal.com/events/nyc",
            title="ETHGlobal NYC",
            sponsors=[Sponsor(name="US Co", website="https://usco.example")],
        ),
        _build_event(
            url="https://ethglobal.com/events/berlin",
            title="ETHGlobal Berlin",
            sponsors=[Sponsor(name="Global Co", website="https://global.example")],
        ),
    ]
    _stub_source_events(pipeline, events)
    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_website",
        lambda sponsor: sponsor.website,
    )
    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_domain",
        lambda sponsor, website: website.split("//", 1)[1],
    )
    monkeypatch.setattr(pipeline.enricher, "validate_website", lambda website: True)
    monkeypatch.setattr(
        pipeline.enricher,
        "find_contact_candidates",
        lambda sponsor, website, domain: [
            ContactCandidate(
                full_name="Jane Doe",
                first_name="Jane",
                last_name="Doe",
                title="Head of Partnerships",
                email=f"jane@{domain}",
                source="public-search-pattern",
                linkedin_url=None,
                confidence=90,
            )
        ],
    )
    monkeypatch.setattr(
        pipeline.validator,
        "validate",
        lambda email: EmailValidation(
            syntax_valid=True,
            mx_valid=True,
            smtp_code=250,
            smtp_message="ok",
        ),
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "qualify",
        lambda sponsor, event, website, domain: CompanyQualification(
            company_segment="AI",
            recently_funded=True,
            recent_funding_signal="Funding found",
            company_location=(
                "San Francisco, US" if sponsor.name == "US Co" else "Berlin, Germany"
            ),
            location_priority="US" if sponsor.name == "US Co" else "Global",
            developer_adoption_need=True,
            market_visibility_need=True,
            qualification_notes="Good fit",
            score=80 if sponsor.name == "US Co" else 95,
            accepted=True,
        ),
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "review_contacts",
        lambda sponsor, event, website, domain, qualification, contacts, validations: {
            contact.email.lower(): ContactReview(
                accepted=True,
                score=80,
                notes="Accepted by contact review.",
            )
            for contact in contacts
        },
    )

    result = pipeline.run(["ethglobal"], ["ai"], 2)

    assert [lead.sponsor_company for lead in result.rows] == ["US Co", "Global Co"]
    assert result.rows[0].location_priority == "US"


def test_pipeline_run_skips_unaccepted_when_precheck_required(
    settings, monkeypatch
) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(
        pipeline,
        [_build_event(sponsors=[Sponsor(name="ENS")])],
    )
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
        validation=_build_validation(
            mx_valid=False,
            smtp_code=550,
            smtp_message="rejected",
        ),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert result.rows == []


def test_pipeline_run_skips_network_precheck_when_disabled(
    settings, monkeypatch
) -> None:
    settings.qualification_enabled = False
    settings.smtp_precheck_required = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[_build_contact(linkedin_url=None)],
    )
    captured = {}

    def validate(email: str, **kwargs) -> EmailValidation:
        captured["kwargs"] = kwargs
        return EmailValidation(
            syntax_valid=True,
            mx_valid=False,
            smtp_code=None,
            smtp_message=None,
        )

    monkeypatch.setattr(pipeline.validator, "validate", validate)

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert captured["kwargs"] == {
        "include_mx_lookup": False,
        "include_smtp_probe": False,
    }
    assert result.rows[0].email_accepted is False


def test_pipeline_run_skips_invalid_website(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(
        pipeline,
        [_build_event(sponsors=[Sponsor(name="ENS")])],
    )
    _stub_enrichment(
        pipeline,
        monkeypatch,
        website_is_valid=False,
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert result.rows == []


def test_pipeline_run_keeps_only_openai_accepted_contacts(
    settings, monkeypatch
) -> None:
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    _stub_enrichment(
        pipeline,
        monkeypatch,
        contacts=[
            _build_contact(email="first@ens.domains", linkedin_url=None),
            _build_contact(email="second@ens.domains", linkedin_url=None),
        ],
    )
    monkeypatch.setattr(
        pipeline.validator,
        "validate",
        lambda email: _build_validation(),
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "qualify",
        lambda sponsor, event, website, domain: CompanyQualification(
            company_segment="Web3",
            recently_funded=True,
            recent_funding_signal="Raised recently",
            company_location="New York, US",
            location_priority="US",
            developer_adoption_need=True,
            market_visibility_need=True,
            qualification_notes="Good fit",
            score=90,
            accepted=True,
        ),
    )
    monkeypatch.setattr(
        pipeline.qualifier,
        "review_contacts",
        lambda sponsor, event, website, domain, qualification, contacts, validations: {
            "first@ens.domains": ContactReview(
                accepted=False,
                score=10,
                notes="Generic fallback contact.",
            ),
            "second@ens.domains": ContactReview(
                accepted=True,
                score=95,
                notes="Best decision-maker match.",
            ),
        },
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert result.rows[0].decision_maker_email == "second@ens.domains"
    assert result.rows[0].contact_review_accepted is True
    assert result.rows[0].contact_review_score == 95


def test_pipeline_validates_contacts_in_parallel(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    _stub_source_events(pipeline, [_build_event()])
    settings.qualification_enabled = False

    active_calls = {"count": 0, "peak": 0}
    lock = threading.Lock()

    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_website",
        lambda sponsor: "https://ens.domains",
    )
    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_domain",
        lambda sponsor, website: "ens.domains",
    )
    monkeypatch.setattr(pipeline.enricher, "validate_website", lambda website: True)
    monkeypatch.setattr(
        pipeline.enricher,
        "find_contact_candidates",
        lambda sponsor, website, domain: [
            _build_contact(email="first@ens.domains", linkedin_url=None),
            _build_contact(email="second@ens.domains", linkedin_url=None),
        ],
    )

    def validate(email: str) -> EmailValidation:
        with lock:
            active_calls["count"] += 1
            active_calls["peak"] = max(active_calls["peak"], active_calls["count"])
        try:
            time.sleep(0.05)
            return _build_validation()
        finally:
            with lock:
                active_calls["count"] -= 1

    monkeypatch.setattr(pipeline.validator, "validate", validate)

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 2
    assert result.rows[0].decision_maker_email == "first@ens.domains"
    assert result.rows[1].decision_maker_email == "second@ens.domains"
    assert active_calls["peak"] > 1


def test_pipeline_run_ignores_source_and_contact_errors(settings) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    pipeline.sources = {
        "broken": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: (
                _ for _ in ()
            ).throw(RuntimeError("boom"))
        )
    }

    result = pipeline.run(["broken"], ["web3"], 1)

    assert result.rows == []
    assert result.export_name.endswith(".xlsx")
    assert pd.read_excel(BytesIO(result.export_bytes)).empty


def test_pipeline_run_with_custom_urls_does_not_mutate_default_sources(
    settings, monkeypatch
) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    builtin_source = SimpleNamespace(
        fetch_events=lambda keywords, limit, progress_callback=None: []
    )
    custom_source = SimpleNamespace(
        fetch_events=lambda keywords, limit, progress_callback=None: []
    )
    pipeline.sources = {"ethglobal": builtin_source}
    monkeypatch.setattr(
        "hackindia_leads.pipeline.build_sources",
        lambda fetcher, search_client, custom_urls=None: {
            "ethglobal": builtin_source,
            "custom": custom_source,
        },
    )

    pipeline.run(["custom"], ["web3"], 1, custom_urls=["https://demo.example"])

    assert pipeline.sources == {"ethglobal": builtin_source}


def test_pipeline_run_stops_before_processing_sources(settings, monkeypatch) -> None:
    settings.qualification_enabled = False
    pipeline = LeadPipeline(settings)
    _stub_source_events(
        pipeline,
        [_build_event(sponsors=[])],
    )
    control = PipelineControl()
    control.stop()

    result = pipeline.run(["ethglobal"], ["web3"], 1, control=control)

    assert result.rows == []
    assert result.export_name.endswith(".xlsx")
    assert pd.read_excel(BytesIO(result.export_bytes)).empty
