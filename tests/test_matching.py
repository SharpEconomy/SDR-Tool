from __future__ import annotations

from growth_engine.intake import BusinessProfileBuilder
from growth_engine.matching import MatchingEngine
from growth_engine.models import (
    ContactPath,
    ContactValidation,
    EnrichedEntity,
    OpportunityScore,
)


def test_matching_engine_prefers_refined_reason_and_best_contact(intake) -> None:
    profile = BusinessProfileBuilder().build(intake)
    entity = EnrichedEntity(
        discovery_mode="partners",
        source_type="public_web",
        source_url="https://example.com",
        entity_name="Example Partner",
        entity_domain="example.com",
        entity_website="https://example.com",
        category="Partnership",
        description="Channel partner for retail growth.",
        location="India",
        company_size="Mid Market",
        budget_signal="Medium",
        trust_signals=["Public profile"],
        timing_signals=["Active"],
        accessibility_signals=["Email available"],
        matched_keywords=["retail", "channel"],
        decision_maker_name="Riya Sharma",
        decision_maker_title="Head of Partnerships",
        decision_maker_email="riya.sharma@example.com",
        contact_paths=[
            ContactPath(
                kind="email",
                value="info@example.com",
                label="info@example.com",
                validation=ContactValidation(True, True),
                source="page_email",
            ),
            ContactPath(
                kind="decision_maker_email",
                value="riya.sharma@example.com",
                label="riya.sharma@example.com (guessed decision-maker)",
                validation=ContactValidation(True, True),
                source="pattern_guess",
            ),
        ],
    )
    score = OpportunityScore(
        fit=80,
        relevance=78,
        geography=90,
        budget_compatibility=76,
        intent=85,
        accessibility=80,
        trust=75,
        timing=72,
        expected_value=82,
        priority_score=84,
        confidence=79,
        explanations=["Strong partner overlap"],
        why_it_matters="High channel-fit for expansion in India.",
        next_action="Email the partnership lead with a distributor proposal.",
    )

    opportunity = MatchingEngine().build_opportunity(profile, entity, score, rank=1)

    assert opportunity.why_it_matters == "High channel-fit for expansion in India."
    assert (
        opportunity.next_action
        == "Email the partnership lead with a distributor proposal."
    )
    assert (
        opportunity.contact_path == "riya.sharma@example.com (guessed decision-maker)"
    )
    assert opportunity.email_validation == "accepted, score 2/2"
