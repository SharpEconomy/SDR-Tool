from __future__ import annotations

from growth_engine.models import BusinessIntake, BusinessProfile, TargetingModel
from growth_engine.services.openai_service import ModelUnavailableError, OpenAIService
from growth_engine.utils import (
    dedupe_keep_order,
    extract_domain,
    keyword_fragments,
    normalize_url,
)

DEFAULT_BUYING_SIGNALS = {
    "customers": ["looking for", "solution", "growth", "expansion", "buyer"],
    "vendors": ["procurement", "supplier", "vendor", "rfq", "tender"],
    "suppliers": ["bulk", "distribution", "manufacturing", "sourcing"],
    "partners": ["channel", "partner", "reseller", "alliances", "ecosystem"],
    "service_providers": ["agency", "consulting", "implementation", "outsourcing"],
}


class BusinessProfileBuilder:
    def __init__(self, openai_service: OpenAIService | None = None) -> None:
        self.openai_service = openai_service

    def build(self, intake: BusinessIntake) -> BusinessProfile:
        normalized_website = normalize_url(intake.website)
        context_keywords = dedupe_keep_order(
            keyword_fragments(intake.ideal_customer_profile)
            + keyword_fragments(intake.opportunity_type_needed)
            + keyword_fragments(intake.vendor_constraints)
            + keyword_fragments(intake.supplier_constraints)
        )
        keywords = dedupe_keep_order(
            intake.inclusion_keywords
            + intake.offerings
            + intake.goals
            + [intake.industry, intake.opportunity_type_needed]
            + context_keywords
        )
        targeting_model = TargetingModel(
            keywords=keywords,
            exclude_keywords=dedupe_keep_order(intake.exclusion_keywords),
            sectors=dedupe_keep_order(intake.preferred_sectors + [intake.industry]),
            company_sizes=dedupe_keep_order(intake.preferred_company_sizes),
            geographies=dedupe_keep_order(
                intake.target_geographies or [intake.location]
            ),
            value_themes=dedupe_keep_order(
                intake.goals
                + intake.offerings
                + [intake.ideal_customer_profile, intake.opportunity_type_needed]
            ),
            buying_signals=self._default_buying_signals(intake.discovery_modes),
        )

        if self.openai_service is not None and self.openai_service.is_available():
            try:
                targeting_model = self._refine_with_model(intake, targeting_model)
            except ModelUnavailableError:
                pass

        return BusinessProfile(
            business_name=intake.business_name.strip(),
            website=normalized_website,
            domain=extract_domain(normalized_website),
            description=intake.description.strip(),
            industry=intake.industry.strip(),
            location=intake.location.strip(),
            target_geographies=dedupe_keep_order(intake.target_geographies),
            budget_label=intake.budget.strip() or "Not specified",
            ideal_customer_profile=intake.ideal_customer_profile.strip(),
            preferred_company_sizes=dedupe_keep_order(intake.preferred_company_sizes),
            preferred_sectors=dedupe_keep_order(intake.preferred_sectors),
            offerings=dedupe_keep_order(intake.offerings),
            goals=dedupe_keep_order(intake.goals),
            discovery_modes=dedupe_keep_order(intake.discovery_modes),
            opportunity_type_needed=intake.opportunity_type_needed.strip(),
            inclusion_keywords=dedupe_keep_order(intake.inclusion_keywords),
            exclusion_keywords=dedupe_keep_order(intake.exclusion_keywords),
            vendor_constraints=intake.vendor_constraints.strip(),
            supplier_constraints=intake.supplier_constraints.strip(),
            user_urls=dedupe_keep_order(intake.user_urls),
            targeting_model=targeting_model,
        )

    def _refine_with_model(
        self,
        intake: BusinessIntake,
        base_model: TargetingModel,
    ) -> TargetingModel:
        payload = {
            "business_name": intake.business_name,
            "description": intake.description,
            "industry": intake.industry,
            "goals": intake.goals,
            "discovery_modes": intake.discovery_modes,
            "base_model": {
                "keywords": base_model.keywords,
                "exclude_keywords": base_model.exclude_keywords,
                "sectors": base_model.sectors,
                "company_sizes": base_model.company_sizes,
                "geographies": base_model.geographies,
                "value_themes": base_model.value_themes,
                "buying_signals": base_model.buying_signals,
            },
        }
        data = self.openai_service.infer_targeting_model(payload)
        return TargetingModel(
            keywords=dedupe_keep_order(data.get("keywords", []) or base_model.keywords),
            exclude_keywords=base_model.exclude_keywords,
            sectors=dedupe_keep_order(data.get("sectors", []) or base_model.sectors),
            company_sizes=dedupe_keep_order(
                data.get("company_sizes", []) or base_model.company_sizes
            ),
            geographies=base_model.geographies,
            value_themes=dedupe_keep_order(
                data.get("value_themes", []) or base_model.value_themes
            ),
            buying_signals=dedupe_keep_order(
                data.get("buying_signals", []) or base_model.buying_signals
            ),
        )

    def _default_buying_signals(self, discovery_modes: list[str]) -> list[str]:
        signals: list[str] = []
        for mode in discovery_modes:
            signals.extend(DEFAULT_BUYING_SIGNALS.get(mode, []))
        return dedupe_keep_order(signals)
