from __future__ import annotations

from datetime import UTC, datetime

from growth_engine.models import (
    DecisionRunResult,
    DiscoveryDocument,
    EnrichedEntity,
    Opportunity,
    OpportunityScore,
)
from growth_engine.orchestration import DecisionEngine, PipelineControl


def test_decision_engine_end_to_end(settings, intake, monkeypatch) -> None:
    engine = DecisionEngine(settings)
    engine.audit_store = type(
        "AuditStore",
        (),
        {"save": lambda self, record: f"firestore://growth_runs/{record.run_id}"},
    )()
    document = DiscoveryDocument(
        adapter_name="public_web",
        source_type="public_web",
        discovery_mode="customers",
        url="https://example.com",
        title="Example Retail",
        snippet="Retail buyer India",
        html="<html><body><h1>Example Retail</h1>hello@example.com</body></html>",
        status_code=200,
        fetched_at=datetime.now(UTC),
    )
    entity = EnrichedEntity(
        discovery_mode="customers",
        source_type="public_web",
        source_url="https://example.com",
        entity_name="Example Retail",
        entity_domain="example.com",
        entity_website="https://example.com",
        category="Retail",
        description="Retail chain across India.",
        location="India",
        company_size="SMB",
        budget_signal="Medium",
        trust_signals=["Public profile"],
        timing_signals=["Active"],
        accessibility_signals=["Email available"],
        matched_keywords=["retail"],
    )
    score = OpportunityScore(70, 60, 90, 60, 88, 70, 65, 60, 72, 80, 70, ["Strong fit"])
    opportunity = Opportunity(
        priority_rank=1,
        discovery_mode="customers",
        market_side="Demand-side",
        entity_name="Example Retail",
        entity_website="https://example.com",
        entity_domain="example.com",
        category="Retail",
        location="India",
        company_size="SMB",
        budget_signal="Medium",
        expected_value="High",
        timing_signal="Active",
        decision_maker=None,
        decision_maker_email=None,
        email_validation="not checked",
        contact_path="hello@example.com",
        source_type="public_web",
        source_url="https://example.com",
        priority_score=80,
        confidence=70,
        why_it_matters="Strong fit",
        reasoning_summary="Fit score 70 | Intent score 88",
        next_action="Reach out",
        score=score,
    )

    monkeypatch.setattr(
        engine, "_discover", lambda profile, progress_callback, log, control: [document]
    )
    monkeypatch.setattr(
        engine,
        "_enrich_documents",
        lambda profile, documents, progress_callback, log, control: ([entity], []),
    )
    monkeypatch.setattr(
        engine,
        "_score_and_match",
        lambda profile, entities, progress_callback, log, control: [opportunity],
    )

    result = engine.run(intake)

    assert isinstance(result, DecisionRunResult)
    assert result.opportunities[0].entity_name == "Example Retail"
    assert result.audit_record.opportunity_count == 1
    assert result.export_uri is None


def test_pipeline_control_pause_resume_stop() -> None:
    control = PipelineControl()

    control.pause()
    control.resume()
    control.stop()

    assert control.should_stop() is True
