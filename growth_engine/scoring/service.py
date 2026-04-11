from __future__ import annotations

from collections.abc import Iterable

from growth_engine.models import BusinessProfile, EnrichedEntity, OpportunityScore
from growth_engine.services.openai_service import (
    ModelUnavailableError,
    OpenAIService,
    bounded_adjustment,
)
from growth_engine.utils import clamp, dedupe_keep_order, keyword_fragments

WEIGHTS = {
    "fit": 0.2,
    "relevance": 0.15,
    "geography": 0.1,
    "budget_compatibility": 0.1,
    "intent": 0.15,
    "accessibility": 0.1,
    "trust": 0.1,
    "timing": 0.05,
    "expected_value": 0.05,
}


class ScoringEngine:
    def __init__(self, openai_service: OpenAIService | None = None) -> None:
        self.openai_service = openai_service

    def score(
        self, profile: BusinessProfile, entity: EnrichedEntity
    ) -> OpportunityScore:
        fit = self._fit_score(profile, entity)
        relevance = self._relevance_score(profile, entity)
        geography = self._geography_score(profile, entity)
        budget = self._budget_score(profile, entity)
        intent = self._intent_score(entity)
        accessibility = clamp(30 + len(entity.accessibility_signals) * 20)
        trust = clamp(25 + len(entity.trust_signals) * 18)
        timing = clamp(35 + len(entity.timing_signals) * 12)
        expected_value = self._expected_value_score(profile, entity, fit, intent)
        confidence = clamp(
            35
            + len(entity.evidence) * 5
            + (15 if entity.decision_maker_email else 0)
            + (10 if entity.entity_domain else 0)
        )
        priority_score = clamp(
            (fit * WEIGHTS["fit"])
            + (relevance * WEIGHTS["relevance"])
            + (geography * WEIGHTS["geography"])
            + (budget * WEIGHTS["budget_compatibility"])
            + (intent * WEIGHTS["intent"])
            + (accessibility * WEIGHTS["accessibility"])
            + (trust * WEIGHTS["trust"])
            + (timing * WEIGHTS["timing"])
            + (expected_value * WEIGHTS["expected_value"])
        )
        explanations = dedupe_keep_order(
            [
                f"Fit score {fit} from sector and offering overlap.",
                f"Relevance score {relevance} using business need, ICP, and matched keywords.",
                f"Intent score {intent} based on timing signals: {', '.join(entity.timing_signals)}.",
                f"Accessibility score {accessibility} from available contact paths.",
                f"Trust score {trust} from public evidence quality.",
            ]
        )
        why_it_matters = (
            f"Matches {profile.business_name}'s {entity.discovery_mode.replace('_', ' ')} need "
            f"through {entity.category.lower()} relevance, {entity.location} reach, and "
            f"{', '.join(entity.matched_keywords[:3]) or 'public business signals'}."
        )
        next_action = (
            "Validate the best contact and prepare a tailored outreach note."
            if entity.contact_paths
            else "Review the source page and confirm a usable contact route."
        )
        return OpportunityScore(
            fit=fit,
            relevance=relevance,
            geography=geography,
            budget_compatibility=budget,
            intent=intent,
            accessibility=accessibility,
            trust=trust,
            timing=timing,
            expected_value=expected_value,
            priority_score=priority_score,
            confidence=confidence,
            explanations=explanations,
            why_it_matters=why_it_matters,
            next_action=next_action,
        )

    def refine_top_scores(
        self,
        profile: BusinessProfile,
        entities_with_scores: list[tuple[EnrichedEntity, OpportunityScore]],
    ) -> list[OpportunityScore]:
        scores = [score for _, score in entities_with_scores]
        if (
            not entities_with_scores
            or self.openai_service is None
            or not self.openai_service.is_available()
        ):
            return scores
        try:
            payload = {
                "business_profile": {
                    "business_name": profile.business_name,
                    "industry": profile.industry,
                    "goals": profile.goals,
                    "target_geographies": profile.target_geographies,
                },
                "opportunities": [
                    {
                        "entity_name": entity.entity_name,
                        "discovery_mode": entity.discovery_mode,
                        "description": entity.description,
                        "location": entity.location,
                        "budget_signal": entity.budget_signal,
                        "matched_keywords": entity.matched_keywords,
                        "timing_signals": entity.timing_signals,
                        "trust_signals": entity.trust_signals,
                        "priority_score": score.priority_score,
                        "confidence": score.confidence,
                    }
                    for entity, score in entities_with_scores
                ],
            }
            data = self.openai_service.refine_scores(payload)
        except ModelUnavailableError:
            return scores

        items = data.get("opportunities", [])
        refined: list[OpportunityScore] = []
        for index, score in enumerate(scores):
            item = (
                items[index]
                if index < len(items) and isinstance(items[index], dict)
                else {}
            )
            refined.append(
                OpportunityScore(
                    fit=score.fit,
                    relevance=score.relevance,
                    geography=score.geography,
                    budget_compatibility=score.budget_compatibility,
                    intent=score.intent,
                    accessibility=score.accessibility,
                    trust=score.trust,
                    timing=score.timing,
                    expected_value=score.expected_value,
                    priority_score=clamp(
                        score.priority_score
                        + bounded_adjustment(item.get("priority_adjustment", 0))
                    ),
                    confidence=clamp(
                        score.confidence
                        + bounded_adjustment(
                            item.get("confidence_adjustment", 0), lower=-15, upper=15
                        )
                    ),
                    explanations=dedupe_keep_order(
                        [
                            *score.explanations,
                            str(item.get("why_it_matters", "")).strip(),
                            str(item.get("next_action", "")).strip(),
                        ]
                    ),
                    why_it_matters=(
                        str(item.get("why_it_matters", "")).strip()
                        or score.why_it_matters
                    ),
                    next_action=(
                        str(item.get("next_action", "")).strip() or score.next_action
                    ),
                )
            )
        return refined

    def _fit_score(self, profile: BusinessProfile, entity: EnrichedEntity) -> int:
        sector_overlap = _overlap(profile.preferred_sectors, [entity.category])
        keyword_overlap = _overlap(
            profile.targeting_model.keywords, entity.matched_keywords
        )
        context_overlap = _overlap(
            self._profile_context_terms(profile, entity),
            entity.matched_keywords
            + entity.evidence
            + [entity.description, entity.category],
        )
        size_alignment = int(
            not profile.preferred_company_sizes
            or entity.company_size in profile.preferred_company_sizes
        )
        return clamp(
            30
            + sector_overlap * 18
            + keyword_overlap * 10
            + context_overlap * 8
            + size_alignment * 12
        )

    def _relevance_score(self, profile: BusinessProfile, entity: EnrichedEntity) -> int:
        matched = len(entity.matched_keywords) * 10
        context_alignment = _overlap(
            self._profile_context_terms(profile, entity),
            entity.evidence + [entity.description, entity.category],
        )
        return clamp(35 + matched + context_alignment * 9)

    def _geography_score(self, profile: BusinessProfile, entity: EnrichedEntity) -> int:
        if not profile.target_geographies:
            return 60
        entity_location = entity.location.lower()
        if any(
            target.lower() in entity_location for target in profile.target_geographies
        ):
            return 90
        if entity.location == "Unknown":
            return 45
        return 55

    def _budget_score(self, profile: BusinessProfile, entity: EnrichedEntity) -> int:
        budget = profile.budget_label.lower()
        signal = entity.budget_signal.lower()
        if budget == "not specified" or signal == "unclear":
            return 55
        if "lean" in budget and "high" in signal:
            return 35
        if "high" in budget and "lean" in signal:
            return 70
        return 78

    def _intent_score(self, entity: EnrichedEntity) -> int:
        signals = " ".join(entity.timing_signals).lower()
        if "active" in signals:
            return 88
        if "emerging" in signals:
            return 72
        return 52

    def _expected_value_score(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
        fit: int,
        intent: int,
    ) -> int:
        high_value_words = " ".join(profile.goals + profile.offerings).lower()
        multiplier = 1.0 + (0.1 if "enterprise" in high_value_words else 0.0)
        if entity.discovery_mode == "partners":
            multiplier += 0.05
        return clamp(((fit * 0.6) + (intent * 0.4)) * multiplier)

    def _profile_context_terms(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
    ) -> list[str]:
        parts = [profile.ideal_customer_profile, profile.opportunity_type_needed]
        if entity.discovery_mode in {"vendors", "service_providers"}:
            parts.append(profile.vendor_constraints)
        if entity.discovery_mode == "suppliers":
            parts.append(profile.supplier_constraints)
        return [part for part in parts if part]


def _overlap(left: Iterable[str], right: Iterable[str]) -> int:
    left_set = {
        token
        for item in left
        if item and item.strip()
        for token in keyword_fragments(item)
    }
    right_set = {
        token
        for item in right
        if item and item.strip()
        for token in keyword_fragments(item)
    }
    return len(left_set & right_set)
