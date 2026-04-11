from __future__ import annotations

import re
from dataclasses import asdict

from growth_engine.models import BusinessIntake, IntakeDraft, IntakeQuestion
from growth_engine.services.openai_service import ModelUnavailableError, OpenAIService
from growth_engine.utils import (
    dedupe_keep_order,
    keyword_fragments,
    normalize_whitespace,
)

LIST_FIELDS = {
    "target_geographies",
    "preferred_company_sizes",
    "preferred_sectors",
    "offerings",
    "goals",
    "discovery_modes",
    "inclusion_keywords",
    "exclusion_keywords",
    "user_urls",
}

REQUIRED_FIELDS = [
    "business_name",
    "description",
    "industry",
    "location",
    "website",
    "discovery_modes",
    "opportunity_type_needed",
    "goals",
    "target_geographies",
    "ideal_customer_profile",
    "preferred_company_sizes",
    "preferred_sectors",
    "budget",
    "offerings",
    "inclusion_keywords",
    "exclusion_keywords",
    "vendor_constraints",
    "supplier_constraints",
]

DISCOVERY_MODE_ALIASES = {
    "customer": "customers",
    "customers": "customers",
    "buyer": "customers",
    "buyers": "customers",
    "partner": "partners",
    "partners": "partners",
    "vendor": "vendors",
    "vendors": "vendors",
    "supplier": "suppliers",
    "suppliers": "suppliers",
    "service provider": "service_providers",
    "service providers": "service_providers",
    "agency": "service_providers",
    "consultant": "service_providers",
}

BUDGET_OPTIONS = {
    "lean": "Lean and careful",
    "careful": "Lean and careful",
    "balanced": "Balanced",
    "growth": "Growth-focused",
    "enterprise": "Enterprise-scale",
    "not specified": "Not specified",
}


class IntakeInterviewer:
    def __init__(self, openai_service: OpenAIService | None = None) -> None:
        self.openai_service = openai_service

    def opening_question(self) -> IntakeQuestion:
        return IntakeQuestion(
            question=(
                "Tell me about the business in your own words. Include the name, "
                "what you sell, the industry, and where you are based."
            ),
            focus_fields=["business_name", "description", "industry", "location"],
            rationale="start_broad",
        )

    def apply_answer(
        self,
        draft: IntakeDraft,
        answer: str,
        *,
        focus_fields: list[str] | None = None,
        transcript: list[dict[str, str]] | None = None,
    ) -> IntakeDraft:
        current_focus = dedupe_keep_order(focus_fields or [])
        updated = self._copy_draft(draft)
        self._merge_update(
            updated,
            self._fallback_extract(answer, current_focus),
            focus_fields=current_focus,
        )
        if self.openai_service is not None and self.openai_service.is_available():
            try:
                model_update = self.openai_service.extract_intake_update(
                    {
                        "draft": self._draft_payload(updated),
                        "latest_answer": answer,
                        "focus_fields": current_focus,
                        "transcript": transcript or [],
                    }
                )
                self._merge_update(
                    updated,
                    model_update,
                    focus_fields=current_focus,
                )
            except ModelUnavailableError:
                pass
        return updated

    def next_question(
        self,
        draft: IntakeDraft,
        *,
        transcript: list[dict[str, str]] | None = None,
    ) -> IntakeQuestion | None:
        missing_fields = self.missing_fields(draft)
        if not missing_fields:
            return None
        if self.openai_service is not None and self.openai_service.is_available():
            try:
                data = self.openai_service.generate_intake_question(
                    {
                        "draft": self._draft_payload(draft),
                        "missing_fields": missing_fields,
                        "transcript": transcript or [],
                    }
                )
                question = normalize_whitespace(str(data.get("question", "")))
                focus_fields = [
                    field
                    for field in data.get("focus_fields", [])
                    if field in missing_fields
                ]
                if question and focus_fields:
                    return IntakeQuestion(
                        question=question,
                        focus_fields=focus_fields,
                        rationale=normalize_whitespace(
                            str(data.get("rationale", "")) or ""
                        ),
                    )
            except ModelUnavailableError:
                pass
        return self._fallback_question(draft, missing_fields)

    def missing_fields(self, draft: IntakeDraft) -> list[str]:
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            value = getattr(draft, field)
            if isinstance(value, list):
                if not value:
                    missing.append(field)
            elif value is None or not normalize_whitespace(str(value)):
                missing.append(field)
        return missing

    def completion_ratio(self, draft: IntakeDraft) -> float:
        missing = len(self.missing_fields(draft))
        return (len(REQUIRED_FIELDS) - missing) / len(REQUIRED_FIELDS)

    def to_business_intake(self, draft: IntakeDraft) -> BusinessIntake:
        return BusinessIntake(
            business_name=normalize_whitespace(draft.business_name or ""),
            website=normalize_whitespace(draft.website or ""),
            description=normalize_whitespace(draft.description or ""),
            industry=normalize_whitespace(draft.industry or ""),
            location=normalize_whitespace(draft.location or ""),
            target_geographies=dedupe_keep_order(draft.target_geographies),
            budget=normalize_whitespace(draft.budget or "Not specified"),
            ideal_customer_profile=normalize_whitespace(
                draft.ideal_customer_profile or ""
            ),
            preferred_company_sizes=dedupe_keep_order(draft.preferred_company_sizes),
            preferred_sectors=dedupe_keep_order(draft.preferred_sectors),
            offerings=dedupe_keep_order(draft.offerings),
            goals=dedupe_keep_order(draft.goals),
            discovery_modes=dedupe_keep_order(draft.discovery_modes),
            opportunity_type_needed=normalize_whitespace(
                draft.opportunity_type_needed or ""
            ),
            inclusion_keywords=dedupe_keep_order(draft.inclusion_keywords),
            exclusion_keywords=dedupe_keep_order(draft.exclusion_keywords),
            vendor_constraints=normalize_whitespace(draft.vendor_constraints or "None"),
            supplier_constraints=normalize_whitespace(
                draft.supplier_constraints or "None"
            ),
            user_urls=dedupe_keep_order(draft.user_urls),
        )

    def _merge_update(
        self,
        draft: IntakeDraft,
        update: dict[str, object],
        *,
        focus_fields: list[str],
    ) -> None:
        for field, value in update.items():
            if not hasattr(draft, field):
                continue
            if field in LIST_FIELDS:
                incoming = self._list_value(value)
                if not incoming:
                    continue
                if field in focus_fields:
                    setattr(draft, field, incoming)
                else:
                    existing = getattr(draft, field)
                    setattr(draft, field, dedupe_keep_order(existing + incoming))
                continue
            if isinstance(value, str):
                cleaned = normalize_whitespace(value)
                if cleaned:
                    setattr(draft, field, cleaned)

    def _fallback_extract(
        self,
        answer: str,
        focus_fields: list[str],
    ) -> dict[str, object]:
        cleaned = normalize_whitespace(answer)
        lowered = cleaned.lower()
        candidate_fields = dedupe_keep_order(
            focus_fields + self._detected_fields(cleaned, lowered)
        )
        update: dict[str, object] = {}

        if "business_name" in candidate_fields:
            business_name = self._extract_business_name(cleaned)
            if business_name:
                update["business_name"] = business_name

        if "description" in candidate_fields and len(cleaned.split()) >= 5:
            update["description"] = cleaned

        if "location" in candidate_fields:
            location = self._extract_location(cleaned)
            if location:
                update["location"] = location

        if "industry" in candidate_fields:
            industry = self._extract_industry(cleaned)
            if industry:
                update["industry"] = industry

        if "website" in candidate_fields:
            website = self._extract_website(cleaned)
            if website:
                update["website"] = website

        if "discovery_modes" in candidate_fields:
            modes = self._extract_discovery_modes(lowered)
            if modes:
                update["discovery_modes"] = modes

        if "budget" in candidate_fields:
            budget = self._extract_budget(lowered)
            if budget:
                update["budget"] = budget

        if "user_urls" in candidate_fields:
            urls = self._extract_urls(cleaned)
            if urls:
                update["user_urls"] = urls

        for field in LIST_FIELDS - {"discovery_modes", "user_urls"}:
            if field not in candidate_fields:
                continue
            values = self._extract_list(cleaned)
            if values:
                update[field] = values

        for field in (
            "opportunity_type_needed",
            "ideal_customer_profile",
            "vendor_constraints",
            "supplier_constraints",
        ):
            if field in candidate_fields and cleaned:
                update[field] = cleaned

        return update

    def _fallback_question(
        self,
        draft: IntakeDraft,
        missing_fields: list[str],
    ) -> IntakeQuestion:
        name = normalize_whitespace(draft.business_name or "the business")
        if any(
            field in missing_fields
            for field in ("business_name", "description", "industry", "location")
        ):
            focus = [
                field
                for field in ("business_name", "description", "industry", "location")
                if field in missing_fields
            ]
            if focus == ["business_name"]:
                return IntakeQuestion(
                    question="What should I call the business in the report?",
                    focus_fields=focus,
                    rationale="fallback_specific",
                )
            if focus == ["description"]:
                return IntakeQuestion(
                    question=f"In one or two lines, what does {name} actually sell?",
                    focus_fields=focus,
                    rationale="fallback_specific",
                )
            if focus == ["industry"]:
                return IntakeQuestion(
                    question="Which industry should I optimize discovery around?",
                    focus_fields=focus,
                    rationale="fallback_specific",
                )
            if focus == ["location"]:
                return IntakeQuestion(
                    question=f"Where is {name} based right now?",
                    focus_fields=focus,
                    rationale="fallback_specific",
                )
            return IntakeQuestion(
                question=(
                    "Give me the missing business basics: name, what you sell, "
                    "industry, and base location."
                ),
                focus_fields=focus,
                rationale="fallback_core",
            )

        if "website" in missing_fields:
            return IntakeQuestion(
                question=(
                    f"What website should I use for {name}? If there is no website "
                    "yet, say 'no website yet'."
                ),
                focus_fields=["website"],
                rationale="fallback_website",
            )

        opportunity_fields = [
            field
            for field in ("discovery_modes", "opportunity_type_needed", "goals")
            if field in missing_fields
        ]
        if opportunity_fields:
            return IntakeQuestion(
                question=(
                    "What should I help you find first, and what outcome matters most? "
                    "You can mention customers, partners, vendors, suppliers, or "
                    "service providers."
                ),
                focus_fields=opportunity_fields,
                rationale="fallback_opportunity",
            )

        if any(
            field in missing_fields
            for field in ("target_geographies", "ideal_customer_profile")
        ):
            focus = [
                field
                for field in ("target_geographies", "ideal_customer_profile")
                if field in missing_fields
            ]
            return IntakeQuestion(
                question=(
                    "Which markets should I focus on, and what does the ideal target "
                    "company look like?"
                ),
                focus_fields=focus,
                rationale="fallback_targeting",
            )

        if any(
            field in missing_fields
            for field in ("preferred_company_sizes", "preferred_sectors")
        ):
            focus = [
                field
                for field in ("preferred_company_sizes", "preferred_sectors")
                if field in missing_fields
            ]
            return IntakeQuestion(
                question=(
                    "Which company sizes and sectors should I lean toward when I rank matches?"
                ),
                focus_fields=focus,
                rationale="fallback_fit",
            )

        if "budget" in missing_fields:
            return IntakeQuestion(
                question=(
                    "How price-sensitive should I assume this search is: lean and "
                    "careful, balanced, growth-focused, or enterprise-scale?"
                ),
                focus_fields=["budget"],
                rationale="fallback_budget",
            )

        if "offerings" in missing_fields:
            return IntakeQuestion(
                question="What exact products or services should I represent when I match opportunities?",
                focus_fields=["offerings"],
                rationale="fallback_offerings",
            )

        if any(
            field in missing_fields
            for field in ("inclusion_keywords", "exclusion_keywords")
        ):
            focus = [
                field
                for field in ("inclusion_keywords", "exclusion_keywords")
                if field in missing_fields
            ]
            return IntakeQuestion(
                question=(
                    "Any must-have words or red-flag words I should use while filtering? "
                    "You can give both."
                ),
                focus_fields=focus,
                rationale="fallback_filters",
            )

        if any(
            field in missing_fields
            for field in ("vendor_constraints", "supplier_constraints")
        ):
            focus = [
                field
                for field in ("vendor_constraints", "supplier_constraints")
                if field in missing_fields
            ]
            return IntakeQuestion(
                question=(
                    "Any vendor or supplier constraints I should enforce, such as "
                    "geography, trust, MOQ, delivery, or compliance expectations?"
                ),
                focus_fields=focus,
                rationale="fallback_constraints",
            )

        return IntakeQuestion(
            question="If you have a few public URLs you already trust, paste them now. Otherwise say skip.",
            focus_fields=["user_urls"],
            rationale="fallback_optional_urls",
        )

    def _detected_fields(self, cleaned: str, lowered: str) -> list[str]:
        detected: list[str] = []
        if self._extract_website(cleaned):
            detected.append("website")
        if self._extract_discovery_modes(lowered):
            detected.append("discovery_modes")
        if self._extract_budget(lowered):
            detected.append("budget")
        if self._extract_urls(cleaned):
            detected.append("user_urls")
        if any(token in lowered for token in ("goal", "need", "want", "looking for")):
            detected.extend(["opportunity_type_needed", "goals"])
        if any(token in lowered for token in ("based in", "from ", "located in")):
            detected.append("location")
        return dedupe_keep_order(detected)

    def _extract_business_name(self, value: str) -> str | None:
        if not value:
            return None
        first_sentence = re.split(r"[.!?]", value, maxsplit=1)[0]
        for pattern in (
            r"^(?:we are|we're|i run|my business is)\s+([^,.;]+)",
            r"^([^,.;]+?)\s+(?:is|are)\s+",
        ):
            match = re.search(pattern, first_sentence, flags=re.IGNORECASE)
            if match:
                candidate = normalize_whitespace(match.group(1))
                if 2 <= len(candidate) <= 80:
                    return candidate
        candidate = normalize_whitespace(first_sentence.split(",")[0])
        if 2 <= len(candidate) <= 80 and len(candidate.split()) <= 6:
            return candidate
        return None

    def _extract_location(self, value: str) -> str | None:
        patterns = (
            r"(?:based in|located in|from)\s+([^.;]+)",
            r"(?:headquartered in)\s+([^.;]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return normalize_whitespace(match.group(1))
        return None

    def _extract_industry(self, value: str) -> str | None:
        patterns = (
            r"(?:industry|sector)\s*(?:is|:)?\s*([^.;]+)",
            r"(?:we are|we're|it is|it's)\s+(?:an?|the)?\s*([^.;,]+?)\s+(?:company|business|brand|manufacturer|startup|firm)",
        )
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return normalize_whitespace(match.group(1))
        return None

    def _extract_website(self, value: str) -> str:
        if "no website" in value.lower():
            return "No website yet"
        tokens = value.replace(",", " ").split()
        for token in tokens:
            if "." in token and " " not in token:
                return token.strip(" .")
        return ""

    def _extract_discovery_modes(self, lowered: str) -> list[str]:
        modes: list[str] = []
        for alias, canonical in DISCOVERY_MODE_ALIASES.items():
            if alias in lowered:
                modes.append(canonical)
        return dedupe_keep_order(modes)

    def _extract_budget(self, lowered: str) -> str | None:
        for keyword, label in BUDGET_OPTIONS.items():
            if keyword in lowered:
                return label
        return None

    def _extract_urls(self, value: str) -> list[str]:
        return dedupe_keep_order(
            [
                item if "://" in item else f"https://{item}"
                for item in re.findall(
                    r"(https?://[^\s,]+|[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s,]*)", value
                )
                if "." in item
            ]
        )

    def _extract_list(self, value: str) -> list[str]:
        normalized = re.sub(r"[\n;|]+", ",", value)
        normalized = re.sub(r"\s+\band\b\s+", ",", normalized, flags=re.IGNORECASE)
        if "," in normalized:
            return dedupe_keep_order(
                [
                    normalize_whitespace(item)
                    for item in normalized.split(",")
                    if normalize_whitespace(item)
                ]
            )
        fragments = keyword_fragments(value, min_length=2)
        return [normalize_whitespace(item) for item in fragments[:5]]

    def _list_value(self, value: object) -> list[str]:
        if isinstance(value, list):
            return dedupe_keep_order([str(item) for item in value if str(item).strip()])
        if isinstance(value, str):
            return self._extract_list(value)
        return []

    def _draft_payload(self, draft: IntakeDraft) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in asdict(draft).items():
            if value in (None, "", []):
                continue
            payload[key] = value
        return payload

    def _copy_draft(self, draft: IntakeDraft) -> IntakeDraft:
        return IntakeDraft(**asdict(draft))
