from __future__ import annotations

import re
from collections.abc import Iterable

from growth_engine.models import (
    BusinessProfile,
    ContactPath,
    EnrichedEntity,
    ParsedDocument,
)
from growth_engine.services.openai_service import ModelUnavailableError, OpenAIService
from growth_engine.services.search import SearchClient
from growth_engine.utils import dedupe_keep_order, extract_domain, normalize_url
from growth_engine.validation.email_validation import EmailValidatorService

ROLE_HINTS = {
    "customers": ["founder", "procurement", "operations", "growth"],
    "vendors": ["sourcing", "procurement", "supply chain", "operations"],
    "suppliers": ["business development", "sales", "distribution"],
    "partners": ["partnerships", "alliances", "channel", "growth"],
    "service_providers": ["founder", "delivery", "consulting", "sales"],
}

SIZE_KEYWORDS = {
    "enterprise": ["enterprise", "fortune", "global", "large"],
    "mid_market": ["mid market", "mid-sized", "midmarket"],
    "smb": ["small business", "smb", "msme", "startup"],
}

BUDGET_KEYWORDS = {
    "high": ["enterprise", "large deal", "strategic", "nationwide"],
    "medium": ["growing", "expansion", "regional"],
    "lean": ["small business", "startup", "cost effective", "low cost"],
}

TIMING_KEYWORDS = {
    "active": ["rfq", "tender", "looking for", "seeking", "now hiring", "partner with"],
    "emerging": ["launch", "expansion", "opening", "new market"],
}


class OpportunityEnricher:
    def __init__(
        self,
        search_client: SearchClient,
        email_validator: EmailValidatorService,
        openai_service: OpenAIService | None = None,
    ) -> None:
        self.search_client = search_client
        self.email_validator = email_validator
        self.openai_service = openai_service

    def enrich(
        self,
        profile: BusinessProfile,
        discovery_mode: str,
        source_type: str,
        source_url: str,
        parsed: ParsedDocument,
        snippet: str,
    ) -> EnrichedEntity:
        entity_website = normalize_url(source_url)
        entity_domain = extract_domain(entity_website)
        entity_name = parsed.likely_entity_name or entity_domain or "Unknown Entity"
        description = parsed.meta_description or parsed.visible_text[:320]
        entity = EnrichedEntity(
            discovery_mode=discovery_mode,
            source_type=source_type,
            source_url=source_url,
            entity_name=entity_name,
            entity_domain=entity_domain,
            entity_website=entity_website,
            category=self._pick_category(parsed.categories, description, snippet),
            description=description,
            location=parsed.likely_location or self._infer_location(parsed, snippet),
            company_size=self._infer_company_size(parsed.visible_text, snippet),
            budget_signal=self._infer_budget_signal(parsed.visible_text, snippet),
            trust_signals=self._trust_signals(parsed),
            timing_signals=self._timing_signals(parsed.visible_text, snippet),
            accessibility_signals=self._accessibility_signals(parsed),
            matched_keywords=self._matched_keywords(profile, parsed, snippet),
            contact_paths=self._build_contact_paths(parsed, entity_domain),
            evidence=dedupe_keep_order(
                [parsed.title, parsed.meta_description, snippet, *parsed.headings[:3]]
            ),
        )

        decision_maker = self._find_decision_maker(
            entity.entity_name, entity.entity_domain, discovery_mode
        )
        entity.decision_maker_name = decision_maker.get("name")
        entity.decision_maker_title = decision_maker.get("title")
        entity.decision_maker_email = decision_maker.get("email")
        if entity.decision_maker_email:
            validation = self.email_validator.validate(
                entity.decision_maker_email,
                include_smtp_probe=False,
            )
            entity.contact_paths.insert(
                0,
                ContactPath(
                    kind="decision_maker_email",
                    value=entity.decision_maker_email,
                    label=f"{entity.decision_maker_email} (guessed decision-maker)",
                    validation=validation,
                    source="pattern_guess",
                ),
            )

        if (
            parsed.ambiguous
            and self.openai_service is not None
            and self.openai_service.is_available()
        ):
            try:
                entity = self._refine_with_model(profile, entity, parsed, snippet)
            except ModelUnavailableError:
                pass

        return self._apply_exclusions(profile, entity)

    def _refine_with_model(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
        parsed: ParsedDocument,
        snippet: str,
    ) -> EnrichedEntity:
        payload = {
            "business_profile": {
                "industry": profile.industry,
                "goals": profile.goals,
                "discovery_modes": profile.discovery_modes,
                "target_keywords": profile.targeting_model.keywords,
            },
            "document": {
                "url": parsed.url,
                "title": parsed.title,
                "meta_description": parsed.meta_description,
                "visible_text": parsed.visible_text[:4000],
                "snippet": snippet,
            },
            "deterministic_entity": {
                "entity_name": entity.entity_name,
                "category": entity.category,
                "description": entity.description,
                "location": entity.location,
                "company_size": entity.company_size,
                "budget_signal": entity.budget_signal,
            },
        }
        data = self.openai_service.extract_entity(payload)
        entity.entity_name = (
            str(data.get("entity_name", entity.entity_name)).strip()
            or entity.entity_name
        )
        entity.category = (
            str(data.get("category", entity.category)).strip() or entity.category
        )
        entity.description = (
            str(data.get("description", entity.description)).strip()
            or entity.description
        )
        entity.location = (
            str(data.get("location", entity.location)).strip() or entity.location
        )
        entity.company_size = (
            str(data.get("company_size", entity.company_size)).strip()
            or entity.company_size
        )
        entity.budget_signal = (
            str(data.get("budget_signal", entity.budget_signal)).strip()
            or entity.budget_signal
        )
        entity.trust_signals = dedupe_keep_order(
            [*entity.trust_signals, *self._safe_list(data.get("trust_signals"))]
        )
        entity.timing_signals = dedupe_keep_order(
            [*entity.timing_signals, *self._safe_list(data.get("timing_signals"))]
        )
        entity.accessibility_signals = dedupe_keep_order(
            [
                *entity.accessibility_signals,
                *self._safe_list(data.get("accessibility_signals")),
            ]
        )
        entity.matched_keywords = dedupe_keep_order(
            [*entity.matched_keywords, *self._safe_list(data.get("matched_keywords"))]
        )
        return entity

    def _build_contact_paths(
        self,
        parsed: ParsedDocument,
        entity_domain: str | None,
    ) -> list[ContactPath]:
        paths: list[ContactPath] = []
        for email in parsed.emails[:3]:
            validation = self.email_validator.validate(email, include_smtp_probe=False)
            paths.append(
                ContactPath(
                    kind="email",
                    value=email,
                    label=email,
                    validation=validation,
                    source="page_email",
                )
            )
        for label, href in parsed.links:
            href_lower = href.lower()
            if (
                "contact" in label.lower()
                or "mailto:" in href_lower
                or "contact" in href_lower
            ):
                value = href.replace("mailto:", "")
                if (
                    entity_domain
                    and value
                    and "@" not in value
                    and value.startswith("/")
                ):
                    value = f"https://{entity_domain}{value}"
                paths.append(
                    ContactPath(
                        kind="contact",
                        value=value,
                        label=label or value,
                        source="contact_link",
                    )
                )
        return paths[:5]

    def _find_decision_maker(
        self,
        entity_name: str,
        entity_domain: str | None,
        discovery_mode: str,
    ) -> dict[str, str | None]:
        if not entity_domain:
            return {"name": None, "title": None, "email": None}
        for hint in ROLE_HINTS.get(discovery_mode, ["founder"]):
            results = self.search_client.search(
                f'site:linkedin.com/in "{entity_name}" "{hint}"', max_results=2
            )
            for result in results:
                parsed = self._parse_linkedin_result(result.title, result.snippet)
                if parsed is None:
                    continue
                return {
                    "name": parsed["name"],
                    "title": parsed["title"],
                    "email": self._guess_email(parsed["name"], entity_domain),
                }
        return {"name": None, "title": None, "email": None}

    def _parse_linkedin_result(self, title: str, snippet: str) -> dict[str, str] | None:
        candidate = title.replace("| LinkedIn", "").replace("- LinkedIn", "").strip()
        parts = [part.strip() for part in candidate.split(" - ") if part.strip()]
        if len(parts) >= 2 and " " in parts[0]:
            return {"name": parts[0], "title": parts[1]}
        snippet_parts = [part.strip() for part in snippet.split(" - ") if part.strip()]
        if len(snippet_parts) >= 2 and " " in snippet_parts[0]:
            return {"name": snippet_parts[0], "title": snippet_parts[1]}
        return None

    def _guess_email(self, full_name: str, domain: str) -> str | None:
        parts = [
            re.sub(r"[^a-z]", "", part.lower()) for part in full_name.split() if part
        ]
        if len(parts) < 2 or not parts[0] or not parts[-1]:
            return None
        return f"{parts[0]}.{parts[-1]}@{domain}"

    def _pick_category(
        self, categories: list[str], description: str, snippet: str
    ) -> str:
        if categories:
            return categories[0].replace("_", " ").title()
        haystack = f"{description} {snippet}".lower()
        if "procurement" in haystack or "rfq" in haystack:
            return "Procurement"
        if "partner" in haystack:
            return "Partnership"
        return "Business Opportunity"

    def _infer_location(self, parsed: ParsedDocument, snippet: str) -> str:
        haystack = (
            f"{parsed.meta_description} {snippet} {parsed.visible_text[:1000]}".lower()
        )
        if "india" in haystack:
            return "India"
        return "Unknown"

    def _infer_company_size(self, *values: str) -> str:
        haystack = " ".join(values).lower()
        for size, keywords in SIZE_KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                return size.replace("_", " ").title()
        return "Unknown"

    def _infer_budget_signal(self, *values: str) -> str:
        haystack = " ".join(values).lower()
        for budget, keywords in BUDGET_KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                return budget.title()
        return "Unclear"

    def _timing_signals(self, *values: str) -> list[str]:
        haystack = " ".join(values).lower()
        signals = []
        for label, keywords in TIMING_KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                signals.append(label.title())
        return signals or ["Unknown timing"]

    def _trust_signals(self, parsed: ParsedDocument) -> list[str]:
        signals = []
        if parsed.meta_description:
            signals.append("Described public profile")
        if parsed.emails:
            signals.append("Direct email listed")
        if any("about" in href.lower() for _, href in parsed.links):
            signals.append("About page path")
        if any("contact" in href.lower() for _, href in parsed.links):
            signals.append("Contact path")
        return signals or ["Limited public trust signals"]

    def _accessibility_signals(self, parsed: ParsedDocument) -> list[str]:
        signals = []
        if parsed.emails:
            signals.append("Email available")
        if parsed.phone_numbers:
            signals.append("Phone available")
        if any("contact" in label.lower() for label, _ in parsed.links):
            signals.append("Contact page available")
        return signals or ["No direct contact path found"]

    def _matched_keywords(
        self,
        profile: BusinessProfile,
        parsed: ParsedDocument,
        snippet: str,
    ) -> list[str]:
        haystack = f"{parsed.visible_text} {snippet}".lower()
        return [
            keyword
            for keyword in profile.targeting_model.keywords
            if keyword.lower() in haystack
        ][:8]

    def _apply_exclusions(
        self, profile: BusinessProfile, entity: EnrichedEntity
    ) -> EnrichedEntity:
        haystack = " ".join(
            [
                entity.entity_name,
                entity.description,
                entity.category,
                entity.location,
                *entity.evidence,
            ]
        ).lower()
        for keyword in profile.exclusion_keywords:
            if keyword.lower() in haystack:
                entity.excluded = True
                entity.exclusion_reason = f"Matched exclusion keyword: {keyword}"
                return entity
        constraint_failure = self._constraint_failure(profile, entity)
        if constraint_failure:
            entity.excluded = True
            entity.exclusion_reason = constraint_failure
            return entity
        return entity

    def _constraint_failure(
        self,
        profile: BusinessProfile,
        entity: EnrichedEntity,
    ) -> str | None:
        relevant_constraints = self._relevant_constraints(
            profile, entity.discovery_mode
        )
        normalized_constraints = relevant_constraints.lower()
        location = entity.location.lower()
        trust = " ".join(entity.trust_signals).lower()
        if any(
            term in normalized_constraints
            for term in ("india-first", "india based", "india-based", "india first")
        ):
            if "india" not in location:
                return "Failed India-based supplier or vendor constraint"
        if (
            "unverified" in normalized_constraints
            and "limited public trust signals" in trust
        ):
            return "Failed verification constraint"
        return None

    def _relevant_constraints(
        self, profile: BusinessProfile, discovery_mode: str
    ) -> str:
        constraint_parts = [
            profile.opportunity_type_needed,
            profile.ideal_customer_profile,
        ]
        if discovery_mode in {"vendors", "service_providers"}:
            constraint_parts.append(profile.vendor_constraints)
        if discovery_mode == "suppliers":
            constraint_parts.append(profile.supplier_constraints)
        return " ".join(part for part in constraint_parts if part)

    def _safe_list(self, value: object) -> list[str]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
