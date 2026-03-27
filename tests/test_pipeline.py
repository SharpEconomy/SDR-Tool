from __future__ import annotations

from types import SimpleNamespace

from hackindia_leads.models import (
    PUBLIC_LEAD_COLUMNS,
    CompanyQualification,
    ContactCandidate,
    EmailValidation,
    Event,
    Sponsor,
)
from hackindia_leads.pipeline import LeadPipeline, PipelineControl, PipelineResult


def test_pipeline_result_dataframe(settings) -> None:
    result = PipelineResult(rows=[], csv_name="empty.csv", csv_bytes=b"")

    frame = result.dataframe()

    assert frame.empty
    assert frame.columns.tolist() == PUBLIC_LEAD_COLUMNS


def test_pipeline_run_writes_only_accepted_leads(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    event = Event(
        source="ethglobal",
        url="https://ethglobal.com/events/mumbai",
        title="ETHGlobal Mumbai",
        sponsors=[
            Sponsor(name="ENS", website="https://ens.domains", evidence="embedded-json")
        ],
    )
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [event]
        )
    }
    monkeypatch.setattr(
        pipeline.enricher, "resolve_website", lambda sponsor: "https://ens.domains"
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
            ContactCandidate(
                full_name="Jane Doe",
                first_name="Jane",
                last_name="Doe",
                title="Head of Partnerships",
                email="jane@ens.domains",
                source="public-search-pattern",
                linkedin_url="https://linkedin.com/in/jane",
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

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert result.rows[0].decision_maker_email == "jane@ens.domains"
    assert result.csv_name.startswith("hackindia_leads_")
    assert result.csv_name.endswith(".csv")
    assert result.csv_bytes.startswith(b"\xef\xbb\xbf")
    csv_text = result.csv_bytes.decode("utf-8-sig")
    assert "jane@ens.domains" in csv_text
    assert "email_smtp_code" not in csv_text
    assert "email_score" not in csv_text
    assert "email_accepted" not in csv_text
    assert "contact_source" not in csv_text


def test_pipeline_run_filters_sponsor_with_failed_gemini_fit(
    settings, monkeypatch
) -> None:
    settings.gemini_api_key = "test-key"
    pipeline = LeadPipeline(settings)
    event = Event(
        source="ethglobal",
        url="https://ethglobal.com/events/mumbai",
        title="ETHGlobal Mumbai",
        sponsors=[Sponsor(name="Example", website="https://example.com")],
    )
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [event]
        )
    }
    monkeypatch.setattr(
        pipeline.enricher, "resolve_website", lambda sponsor: "https://example.com"
    )
    monkeypatch.setattr(
        pipeline.enricher,
        "resolve_domain",
        lambda sponsor, website: "example.com",
    )
    monkeypatch.setattr(pipeline.enricher, "validate_website", lambda website: True)
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


def test_pipeline_run_skips_gemini_when_disabled(settings, monkeypatch) -> None:
    settings.gemini_api_key = "test-key"
    settings.gemini_enabled = False
    pipeline = LeadPipeline(settings)
    event = Event(
        source="ethglobal",
        url="https://ethglobal.com/events/mumbai",
        title="ETHGlobal Mumbai",
        sponsors=[Sponsor(name="ENS", website="https://ens.domains")],
    )
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [event]
        )
    }
    monkeypatch.setattr(
        pipeline.enricher, "resolve_website", lambda sponsor: "https://ens.domains"
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
            ContactCandidate(
                full_name="Jane Doe",
                first_name="Jane",
                last_name="Doe",
                title="Head of Partnerships",
                email="jane@ens.domains",
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
        lambda sponsor, event, website, domain: (_ for _ in ()).throw(
            AssertionError("Gemini should be skipped when disabled")
        ),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert len(result.rows) == 1
    assert result.rows[0].qualification_accepted is True
    assert result.rows[0].company_segment is None


def test_pipeline_run_sorts_us_and_india_fit_first(settings, monkeypatch) -> None:
    settings.gemini_api_key = "test-key"
    pipeline = LeadPipeline(settings)
    events = [
        Event(
            source="ethglobal",
            url="https://ethglobal.com/events/nyc",
            title="ETHGlobal NYC",
            sponsors=[Sponsor(name="US Co", website="https://usco.example")],
        ),
        Event(
            source="ethglobal",
            url="https://ethglobal.com/events/berlin",
            title="ETHGlobal Berlin",
            sponsors=[Sponsor(name="Global Co", website="https://global.example")],
        ),
    ]
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: events
        )
    }
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

    result = pipeline.run(["ethglobal"], ["ai"], 2)

    assert [lead.sponsor_company for lead in result.rows] == ["US Co", "Global Co"]
    assert result.rows[0].location_priority == "US"


def test_pipeline_run_skips_unaccepted_when_precheck_required(
    settings, monkeypatch
) -> None:
    pipeline = LeadPipeline(settings)
    event = Event(
        source="ethglobal",
        url="https://ethglobal.com/events/mumbai",
        title="ETHGlobal Mumbai",
        sponsors=[Sponsor(name="ENS")],
    )
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [event]
        )
    }
    monkeypatch.setattr(
        pipeline.enricher, "resolve_website", lambda sponsor: "https://ens.domains"
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
            ContactCandidate(
                full_name="Jane Doe",
                first_name="Jane",
                last_name="Doe",
                title="Head of Partnerships",
                email="jane@ens.domains",
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
            mx_valid=False,
            smtp_code=550,
            smtp_message="rejected",
        ),
    )

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert result.rows == []


def test_pipeline_run_skips_invalid_website(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    event = Event(
        source="ethglobal",
        url="https://ethglobal.com/events/mumbai",
        title="ETHGlobal Mumbai",
        sponsors=[Sponsor(name="ENS")],
    )
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [event]
        )
    }
    monkeypatch.setattr(
        pipeline.enricher, "resolve_website", lambda sponsor: "https://ens.domains"
    )
    monkeypatch.setattr(pipeline.enricher, "validate_website", lambda website: False)

    result = pipeline.run(["ethglobal"], ["web3"], 1)

    assert result.rows == []


def test_pipeline_run_ignores_source_and_contact_errors(settings, monkeypatch) -> None:
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
    assert result.csv_name.endswith(".csv")
    assert result.csv_bytes.startswith(b"\xef\xbb\xbf")


def test_pipeline_run_stops_before_processing_sources(settings, monkeypatch) -> None:
    pipeline = LeadPipeline(settings)
    pipeline.sources = {
        "ethglobal": SimpleNamespace(
            fetch_events=lambda keywords, limit, progress_callback=None: [
                Event(
                    source="ethglobal",
                    url="https://ethglobal.com/events/mumbai",
                    title="ETHGlobal Mumbai",
                )
            ]
        )
    }
    control = PipelineControl()
    control.stop()

    result = pipeline.run(["ethglobal"], ["web3"], 1, control=control)

    assert result.rows == []
    assert result.csv_name.endswith(".csv")
    assert result.csv_bytes.startswith(b"\xef\xbb\xbf")
