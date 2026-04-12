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
    "website",
    "description",
    "industry",
    "location",
    "discovery_modes",
    "opportunity_type_needed",
    "goals",
    "target_geographies",
    "ideal_customer_profile",
    "preferred_company_sizes",
    "preferred_sectors",
    "budget",
    "offerings",
]

QUESTION_FIELD_LABELS = {
    "business_name": "Name",
    "website": "Website",
    "description": "What you sell",
    "industry": "Industry",
    "location": "Base location",
    "discovery_modes": "Opportunity types",
    "opportunity_type_needed": "Primary need",
    "goals": "Goals",
    "target_geographies": "Target markets",
    "ideal_customer_profile": "Ideal customer profile",
    "preferred_company_sizes": "Preferred company sizes",
    "preferred_sectors": "Preferred sectors",
    "budget": "Budget comfort",
    "offerings": "Offerings",
    "inclusion_keywords": "Must-have keywords",
    "exclusion_keywords": "Avoid keywords",
    "vendor_constraints": "Vendor constraints",
    "supplier_constraints": "Supplier constraints",
    "user_urls": "Trusted URLs",
}

QUESTION_PLAN = (
    (
        "plan_business",
        (
            "business_name",
            "website",
            "description",
            "industry",
            "location",
        ),
        "Reply in one block:",
    ),
    (
        "plan_opportunity",
        (
            "discovery_modes",
            "opportunity_type_needed",
            "goals",
        ),
        "Reply in one block:",
    ),
    (
        "plan_target_market",
        (
            "target_geographies",
            "ideal_customer_profile",
        ),
        "Reply in one block:",
    ),
    (
        "plan_fit",
        (
            "preferred_company_sizes",
            "preferred_sectors",
            "offerings",
        ),
        "Reply in one block:",
    ),
    (
        "plan_commercial",
        (
            "budget",
            "inclusion_keywords",
            "exclusion_keywords",
            "vendor_constraints",
            "supplier_constraints",
        ),
        "Reply in one block. Write `None` if a field does not matter:",
    ),
    (
        "plan_final_sweep",
        tuple(REQUIRED_FIELDS),
        "Reply only with these missing labels:",
    ),
)

FIELD_LABEL_ALIASES = {
    "business_name": {"name", "business name", "company name", "business"},
    "website": {"website", "site", "url", "domain"},
    "description": {"what you sell", "description", "offer", "business description"},
    "industry": {"industry", "sector"},
    "location": {"base location", "location", "hq", "headquarters"},
    "discovery_modes": {"opportunity types", "discovery modes", "who to find"},
    "opportunity_type_needed": {
        "primary need",
        "opportunity need",
        "need",
    },
    "goals": {"goals", "goal", "outcomes", "objective"},
    "target_geographies": {
        "target markets",
        "markets",
        "target geographies",
        "geographies",
        "regions",
    },
    "ideal_customer_profile": {
        "ideal customer profile",
        "icp",
        "ideal target",
    },
    "preferred_company_sizes": {
        "preferred company sizes",
        "company sizes",
        "sizes",
    },
    "preferred_sectors": {"preferred sectors", "sectors", "target sectors"},
    "budget": {"budget comfort", "budget", "price sensitivity"},
    "offerings": {"offerings", "products", "services"},
    "inclusion_keywords": {
        "must-have keywords",
        "inclusion keywords",
        "include",
    },
    "exclusion_keywords": {
        "avoid keywords",
        "exclusion keywords",
        "exclude",
    },
    "vendor_constraints": {"vendor constraints", "vendor rules"},
    "supplier_constraints": {"supplier constraints", "supplier rules"},
    "user_urls": {"trusted urls", "seed urls", "urls"},
}

NONEISH_VALUES = {
    "na",
    "n/a",
    "no",
    "none",
    "not applicable",
    "not important",
    "skip",
}

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
        return self._build_planned_question(
            QUESTION_PLAN[0][0],
            list(QUESTION_PLAN[0][1]),
            QUESTION_PLAN[0][2],
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
        answered_questions = self._answered_question_count(transcript or [])
        for (
            rationale,
            planned_fields,
            prompt_intro,
        ) in QUESTION_PLAN[answered_questions:]:
            focus_fields = [
                field for field in planned_fields if field in missing_fields
            ]
            if focus_fields:
                return self._build_planned_question(
                    rationale,
                    focus_fields,
                    prompt_intro,
                )
        return None

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
        update = {
            field: value
            for field, value in self._extract_structured_answers(answer).items()
            if field in candidate_fields
        }

        if "business_name" in candidate_fields and "business_name" not in update:
            business_name = self._extract_business_name(cleaned)
            if business_name:
                update["business_name"] = business_name

        if (
            "description" in candidate_fields
            and "description" not in update
            and len(cleaned.split()) >= 5
        ):
            update["description"] = cleaned

        if "location" in candidate_fields and "location" not in update:
            location = self._extract_location(cleaned)
            if location:
                update["location"] = location

        if "industry" in candidate_fields and "industry" not in update:
            industry = self._extract_industry(cleaned)
            if industry:
                update["industry"] = industry

        if "website" in candidate_fields and "website" not in update:
            website = self._extract_website(cleaned)
            if website:
                update["website"] = website

        if "discovery_modes" in candidate_fields and "discovery_modes" not in update:
            modes = self._extract_discovery_modes(lowered)
            if modes:
                update["discovery_modes"] = modes

        if "budget" in candidate_fields and "budget" not in update:
            budget = self._extract_budget(lowered)
            if budget:
                update["budget"] = budget

        if "user_urls" in candidate_fields and "user_urls" not in update:
            urls = self._extract_urls(cleaned)
            if urls:
                update["user_urls"] = urls

        for field in LIST_FIELDS - {"discovery_modes", "user_urls"}:
            if field not in candidate_fields or field in update:
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
            if field in candidate_fields and field not in update and cleaned:
                update[field] = cleaned

        return update

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

    def _build_planned_question(
        self,
        rationale: str,
        focus_fields: list[str],
        prompt_intro: str,
    ) -> IntakeQuestion:
        prompt_lines = "\n".join(
            f"{QUESTION_FIELD_LABELS[field]}:" for field in focus_fields
        )
        return IntakeQuestion(
            question=f"{prompt_intro}\n```text\n{prompt_lines}\n```",
            focus_fields=focus_fields,
            rationale=rationale,
        )

    def _answered_question_count(self, transcript: list[dict[str, str]]) -> int:
        return sum(1 for item in transcript if item.get("role") == "user")

    def _extract_structured_answers(self, answer: str) -> dict[str, object]:
        update: dict[str, object] = {}
        alias_lookup = {
            alias: field
            for field, aliases in FIELD_LABEL_ALIASES.items()
            for alias in aliases
        }
        label_pattern = "|".join(
            re.escape(alias) for alias in sorted(alias_lookup, key=len, reverse=True)
        )
        matches = list(
            re.finditer(
                rf"(?i)(?P<label>{label_pattern})\s*:",
                answer,
            )
        )
        for index, match in enumerate(matches):
            field = alias_lookup.get(normalize_whitespace(match.group("label")).lower())
            if field is None:
                continue
            value_start = match.end()
            value_end = (
                matches[index + 1].start() if index + 1 < len(matches) else len(answer)
            )
            raw_value = answer[value_start:value_end]
            parsed_value = self._coerce_structured_value(field, raw_value)
            if parsed_value in (None, "", []):
                continue
            update[field] = parsed_value
        return update

    def _coerce_structured_value(self, field: str, raw_value: str) -> object:
        cleaned = normalize_whitespace(raw_value)
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if field in {"vendor_constraints", "supplier_constraints"}:
            return "None" if lowered in NONEISH_VALUES else cleaned
        if field == "website":
            website = self._extract_website(cleaned)
            return website or cleaned
        if field == "discovery_modes":
            modes = self._extract_discovery_modes(lowered)
            return modes or self._extract_list(cleaned)
        if field == "budget":
            return self._extract_budget(lowered) or cleaned
        if field == "user_urls":
            return self._extract_urls(cleaned)
        if field in LIST_FIELDS:
            if lowered in NONEISH_VALUES:
                return []
            return self._extract_list(cleaned)
        return cleaned

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
            (
                r"(?:we are|we're|it is|it's)\s+(?:an?|the)?\s*([^.;,]+?)\s+"
                r"(?:company|business|brand|manufacturer|startup|firm)"
            ),
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
