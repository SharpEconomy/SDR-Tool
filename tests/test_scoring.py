from __future__ import annotations

from growth_engine.intake import BusinessProfileBuilder
from growth_engine.models import EnrichedEntity
from growth_engine.scoring import ScoringEngine


class _FakeOpenAIService:
    def is_available(self) -> bool:
        return True

    def refine_scores(self, payload):
        return {
            "opportunities": [
                {
                    "priority_adjustment": 5,
                    "confidence_adjustment": 3,
                    "why_it_matters": "Fresh match for expansion.",
                    "next_action": "Call the distributor.",
                }
            ]
        }


def _build_entity() -> EnrichedEntity:
    return EnrichedEntity(
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
        trust_signals=["Contact path", "Public profile"],
        timing_signals=["Active"],
        accessibility_signals=["Email available"],
        matched_keywords=["retail", "distribution"],
        decision_maker_name="Riya Sharma",
        decision_maker_title="Head of Partnerships",
        decision_maker_email="riya.sharma@example.com",
    )


def test_scoring_engine_scores_and_refines(intake) -> None:
    profile = BusinessProfileBuilder().build(intake)
    engine = ScoringEngine(_FakeOpenAIService())
    base_score = engine.score(profile, _build_entity())

    refined = engine.refine_top_scores(profile, [(_build_entity(), base_score)])

    assert base_score.priority_score >= 60
    assert refined[0].priority_score == base_score.priority_score + 5
    assert refined[0].confidence == base_score.confidence + 3
