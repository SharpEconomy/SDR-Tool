from __future__ import annotations

from growth_engine.models import (
    BusinessProfile,
    EnrichedEntity,
    Opportunity,
    OpportunityScore,
)

MARKET_SIDE = {
    "customers": "Demand-side",
    "vendors": "Supply-side",
    "suppliers": "Supply-side",
    "partners": "Ecosystem",
    "service_providers": "Supply-side",
}


class MatchingEngine:
    def build_opportunity(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
        score: OpportunityScore,
        *,
        rank: int,
    ) -> Opportunity:
        best_contact = self._best_contact_path(entity)
        validation = self._validation_label(best_contact)
        contact_path = (
            best_contact.label if best_contact is not None else "No direct path"
        )
        return Opportunity(
            priority_rank=rank,
            discovery_mode=entity.discovery_mode,
            market_side=MARKET_SIDE.get(entity.discovery_mode, "Opportunity"),
            entity_name=entity.entity_name,
            entity_website=entity.entity_website,
            entity_domain=entity.entity_domain,
            category=entity.category,
            location=entity.location,
            company_size=entity.company_size,
            budget_signal=entity.budget_signal,
            expected_value=self._expected_value_label(score.priority_score),
            timing_signal=", ".join(entity.timing_signals[:2]),
            decision_maker=(
                f"{entity.decision_maker_name} ({entity.decision_maker_title})"
                if entity.decision_maker_name and entity.decision_maker_title
                else entity.decision_maker_name
            ),
            decision_maker_email=entity.decision_maker_email,
            email_validation=validation,
            contact_path=contact_path,
            source_type=entity.source_type,
            source_url=entity.source_url,
            priority_score=score.priority_score,
            confidence=score.confidence,
            why_it_matters=score.why_it_matters
            or self._fallback_reason(profile, entity, score),
            reasoning_summary=" | ".join(score.explanations[:4]),
            next_action=score.next_action or self._next_action(entity),
            score=score,
        )

    def _next_action(self, entity: EnrichedEntity) -> str:
        if entity.decision_maker_email:
            return f"Send a tailored outreach note to {entity.decision_maker_email}."
        if entity.contact_paths:
            return f"Review the primary contact path: {entity.contact_paths[0].label}."
        return "Review the source page manually before outreach."

    def _expected_value_label(self, priority_score: int) -> str:
        if priority_score >= 80:
            return "High"
        if priority_score >= 60:
            return "Medium"
        return "Monitor"

    def _best_contact_path(self, entity: EnrichedEntity):
        ranked = sorted(
            entity.contact_paths,
            key=lambda path: (
                path.kind == "decision_maker_email",
                bool(path.validation and path.validation.accepted),
                path.validation.score if path.validation is not None else 0,
            ),
            reverse=True,
        )
        return ranked[0] if ranked else None

    def _validation_label(self, contact_path) -> str:
        if contact_path is None or contact_path.validation is None:
            return "not checked"
        validation = contact_path.validation
        state = "accepted" if validation.accepted else "needs review"
        return f"{state}, score {validation.score}/3"

    def _fallback_reason(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
        score: OpportunityScore,
    ) -> str:
        return (
            f"Strong {entity.discovery_mode.replace('_', ' ')} match for {profile.business_name}: "
            f"{entity.category.lower()} signal, {entity.location}, priority {score.priority_score}/100."
        )
