from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, TypedDict

from growth_engine.models import DISCOVERY_MODES, IntakeDraft
from growth_engine.utils import dedupe_keep_order, normalize_whitespace, slugify

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
WRAPPED_LIST_FIELDS = {"user_urls"}
MULTILINE_FIELDS = {"description", "ideal_customer_profile"}
FIELD_LABELS = {
    "business_name": "Business name",
    "website": "Website",
    "description": "What you sell",
    "industry": "Industry",
    "location": "Base location",
    "target_geographies": "Target markets",
    "budget": "Budget comfort",
    "ideal_customer_profile": "Ideal customer profile",
    "preferred_company_sizes": "Preferred company sizes",
    "preferred_sectors": "Preferred sectors",
    "offerings": "Offerings",
    "goals": "Goals",
    "discovery_modes": "Opportunity types",
    "opportunity_type_needed": "Primary need",
    "inclusion_keywords": "Must-have keywords",
    "exclusion_keywords": "Avoid keywords",
    "vendor_constraints": "Vendor constraints",
    "supplier_constraints": "Supplier constraints",
    "user_urls": "Trusted URLs",
}
FIELD_HELP_TEXT = {
    "business_name": "The company name that should be saved.",
    "website": "Primary public website for this business.",
    "description": "Plain-language summary of what the business sells.",
    "industry": "Best-fit business category.",
    "location": "Primary business base or headquarters.",
    "target_geographies": "Comma-separated markets this business should focus on.",
    "budget": "Budget posture inferred from the public profile. Edit if you know better.",
    "ideal_customer_profile": "Who this business should most likely target.",
    "preferred_company_sizes": "Comma-separated company size targets.",
    "preferred_sectors": "Comma-separated sectors to prioritize.",
    "offerings": "Comma-separated products or services.",
    "goals": "Comma-separated business outcomes or priorities.",
    "discovery_modes": "Comma-separated opportunity types such as customers or partners.",
    "opportunity_type_needed": "The main type of opportunity the business wants next.",
    "inclusion_keywords": "Comma-separated must-match terms.",
    "exclusion_keywords": "Comma-separated terms to avoid.",
    "vendor_constraints": "Rules or limits for vendors.",
    "supplier_constraints": "Rules or limits for suppliers.",
    "user_urls": "One trusted URL per line.",
}
FIELD_ORDER = (
    "business_name",
    "website",
    "description",
    "industry",
    "location",
    "target_geographies",
    "budget",
    "ideal_customer_profile",
    "preferred_company_sizes",
    "preferred_sectors",
    "offerings",
    "goals",
    "discovery_modes",
    "opportunity_type_needed",
    "inclusion_keywords",
    "exclusion_keywords",
    "vendor_constraints",
    "supplier_constraints",
    "user_urls",
)


class SummaryCardConfig(TypedDict):
    id: str
    title: str
    subtitle: str
    fields: tuple[str, ...]


class SummaryRow(TypedDict):
    field_name: str
    label: str
    kind: str
    value: Any
    wrap: bool


class SummaryCard(TypedDict):
    id: str
    title: str
    subtitle: str
    rows: list[SummaryRow]


SUMMARY_CARD_CONFIGS: tuple[SummaryCardConfig, ...] = (
    {
        "id": "business_snapshot",
        "title": "Business snapshot",
        "subtitle": "What this company appears to be",
        "fields": ("description", "industry", "location", "website"),
    },
    {
        "id": "best_fit_market",
        "title": "Best-fit market",
        "subtitle": "Who this business should likely go after",
        "fields": (
            "target_geographies",
            "ideal_customer_profile",
            "preferred_company_sizes",
            "preferred_sectors",
        ),
    },
    {
        "id": "commercial_setup",
        "title": "Commercial setup",
        "subtitle": "What both workflows will use downstream",
        "fields": (
            "offerings",
            "goals",
            "discovery_modes",
            "opportunity_type_needed",
            "inclusion_keywords",
            "exclusion_keywords",
            "vendor_constraints",
            "supplier_constraints",
            "user_urls",
        ),
    },
)


def get_summary_card_config(card_id: str) -> SummaryCardConfig | None:
    for config in SUMMARY_CARD_CONFIGS:
        if config["id"] == card_id:
            return config
    return None


def build_summary_cards(draft: IntakeDraft) -> list[SummaryCard]:
    cards: list[SummaryCard] = []
    for config in SUMMARY_CARD_CONFIGS:
        cards.append(
            {
                "id": config["id"],
                "title": config["title"],
                "subtitle": config["subtitle"],
                "rows": build_summary_rows(config["fields"], draft),
            }
        )
    return cards


def build_summary_rows(fields: tuple[str, ...], draft: IntakeDraft) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for field_name in fields:
        value = getattr(draft, field_name)
        if should_hide_summary_field(value):
            continue
        if field_name == "description":
            rows.append(
                {
                    "field_name": field_name,
                    "label": FIELD_LABELS[field_name],
                    "kind": "paragraph",
                    "value": friendly_value(value, "Description not confirmed yet."),
                    "wrap": False,
                }
            )
            continue
        if isinstance(value, list):
            rows.append(
                {
                    "field_name": field_name,
                    "label": FIELD_LABELS[field_name],
                    "kind": "chips",
                    "value": dedupe_keep_order(value),
                    "wrap": field_name in WRAPPED_LIST_FIELDS,
                }
            )
            continue
        rows.append(
            {
                "field_name": field_name,
                "label": FIELD_LABELS[field_name],
                "kind": "text",
                "value": friendly_value(value),
                "wrap": False,
            }
        )
    return rows


def friendly_value(value: object, fallback: str = "Not confirmed") -> str:
    cleaned = normalize_whitespace(str(value or ""))
    return cleaned or fallback


def should_hide_summary_field(value: object) -> bool:
    if isinstance(value, list):
        return len(dedupe_keep_order([str(item) for item in value])) == 0
    cleaned = normalize_whitespace(str(value or "")).lower()
    return cleaned in {"", "none", "not specified", "not confirmed"}


def build_research_document_id(business_name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{slugify(business_name) or 'business-profile'}-{stamp}"


def normalize_error_message(raw_value: object, *, fallback: str) -> str | None:
    if raw_value is None:
        return None
    cleaned = normalize_whitespace(str(raw_value))
    return cleaned or fallback


def serialize_list_field(value: object) -> str:
    if isinstance(value, list):
        cleaned = dedupe_keep_order(
            [str(item) for item in value if normalize_whitespace(str(item))]
        )
        separator = "\n" if any("://" in str(item) for item in value) else ", "
        return separator.join(cleaned)
    return normalize_whitespace(str(value or ""))


def parse_list_input(raw_value: str) -> list[str]:
    return dedupe_keep_order(
        [
            item
            for item in raw_value.replace("\n", ",").split(",")
            if normalize_whitespace(item)
        ]
    )


def parse_multiline_urls(raw_value: str) -> list[str]:
    items = [normalize_whitespace(line) for line in raw_value.splitlines()]
    cleaned = []
    for item in items:
        if not item:
            continue
        cleaned.append(item if "://" in item else f"https://{item}")
    return dedupe_keep_order(cleaned)


def coerce_field_value(field_name: str, raw_value: object) -> object:
    if field_name in LIST_FIELDS:
        if field_name == "user_urls":
            return parse_multiline_urls(str(raw_value or ""))
        return parse_list_input(str(raw_value or ""))
    return normalize_whitespace(str(raw_value or ""))


def update_draft_from_partial_values(
    draft: IntakeDraft,
    values: dict[str, object],
) -> IntakeDraft:
    updated = IntakeDraft(**asdict(draft))
    for field_name, raw_value in values.items():
        setattr(updated, field_name, coerce_field_value(field_name, raw_value))
    return updated


def draft_from_values(values: dict[str, object]) -> IntakeDraft:
    return IntakeDraft(
        business_name=normalize_whitespace(str(values["business_name"] or "")),
        website=normalize_whitespace(str(values["website"] or "")),
        description=normalize_whitespace(str(values["description"] or "")),
        industry=normalize_whitespace(str(values["industry"] or "")),
        location=normalize_whitespace(str(values["location"] or "")),
        target_geographies=parse_list_input(str(values["target_geographies"] or "")),
        budget=normalize_whitespace(str(values["budget"] or "")),
        ideal_customer_profile=normalize_whitespace(
            str(values["ideal_customer_profile"] or "")
        ),
        preferred_company_sizes=parse_list_input(
            str(values["preferred_company_sizes"] or "")
        ),
        preferred_sectors=parse_list_input(str(values["preferred_sectors"] or "")),
        offerings=parse_list_input(str(values["offerings"] or "")),
        goals=parse_list_input(str(values["goals"] or "")),
        discovery_modes=parse_list_input(str(values["discovery_modes"] or "")),
        opportunity_type_needed=normalize_whitespace(
            str(values["opportunity_type_needed"] or "")
        ),
        inclusion_keywords=parse_list_input(str(values["inclusion_keywords"] or "")),
        exclusion_keywords=parse_list_input(str(values["exclusion_keywords"] or "")),
        vendor_constraints=normalize_whitespace(
            str(values["vendor_constraints"] or "")
        ),
        supplier_constraints=normalize_whitespace(
            str(values["supplier_constraints"] or "")
        ),
        user_urls=parse_multiline_urls(str(values["user_urls"] or "")),
    )


def form_initial_for_fields(
    draft: IntakeDraft,
    field_names: tuple[str, ...] | list[str],
) -> dict[str, str]:
    return {
        field_name: (
            serialize_list_field(getattr(draft, field_name))
            if field_name in LIST_FIELDS
            else normalize_whitespace(str(getattr(draft, field_name) or ""))
        )
        for field_name in field_names
    }


def format_discovery_mode_label(mode: str) -> str:
    return mode.replace("_", " ").title()


def clean_requested_modes(raw_values: list[str]) -> list[str]:
    allowed = {mode for mode in DISCOVERY_MODES}
    return [value for value in dedupe_keep_order(raw_values) if value in allowed]
