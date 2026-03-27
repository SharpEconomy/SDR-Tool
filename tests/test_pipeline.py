from __future__ import annotations

from types import SimpleNamespace

from hackindia_leads.models import (
    PUBLIC_LEAD_COLUMNS,
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
