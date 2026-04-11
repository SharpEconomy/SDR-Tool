from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DISCOVERY_MODES = [
    "customers",
    "vendors",
    "suppliers",
    "partners",
    "service_providers",
]

EXPORT_OPPORTUNITY_COLUMNS = [
    "priority_rank",
    "priority_score",
    "confidence",
    "discovery_mode",
    "market_side",
    "entity_name",
    "entity_website",
    "entity_domain",
    "category",
    "location",
    "company_size",
    "budget_signal",
    "expected_value",
    "timing_signal",
    "decision_maker",
    "decision_maker_email",
    "email_validation",
    "contact_path",
    "source_type",
    "source_url",
    "why_it_matters",
    "reasoning_summary",
    "next_action",
]

EXPORT_SKIPPED_COLUMNS = [
    "discovery_mode",
    "entity_name",
    "entity_website",
    "source_type",
    "source_url",
    "reason",
]


@dataclass(slots=True)
class BusinessIntake:
    business_name: str
    website: str
    description: str
    industry: str
    location: str
    target_geographies: list[str]
    budget: str
    ideal_customer_profile: str
    preferred_company_sizes: list[str]
    preferred_sectors: list[str]
    offerings: list[str]
    goals: list[str]
    discovery_modes: list[str]
    opportunity_type_needed: str
    inclusion_keywords: list[str]
    exclusion_keywords: list[str]
    vendor_constraints: str
    supplier_constraints: str
    user_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IntakeDraft:
    business_name: str | None = None
    website: str | None = None
    description: str | None = None
    industry: str | None = None
    location: str | None = None
    target_geographies: list[str] = field(default_factory=list)
    budget: str | None = None
    ideal_customer_profile: str | None = None
    preferred_company_sizes: list[str] = field(default_factory=list)
    preferred_sectors: list[str] = field(default_factory=list)
    offerings: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    discovery_modes: list[str] = field(default_factory=list)
    opportunity_type_needed: str | None = None
    inclusion_keywords: list[str] = field(default_factory=list)
    exclusion_keywords: list[str] = field(default_factory=list)
    vendor_constraints: str | None = None
    supplier_constraints: str | None = None
    user_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IntakeQuestion:
    question: str
    focus_fields: list[str]
    rationale: str | None = None


@dataclass(slots=True)
class TargetingModel:
    keywords: list[str]
    exclude_keywords: list[str]
    sectors: list[str]
    company_sizes: list[str]
    geographies: list[str]
    value_themes: list[str]
    buying_signals: list[str]


@dataclass(slots=True)
class BusinessProfile:
    business_name: str
    website: str | None
    domain: str | None
    description: str
    industry: str
    location: str
    target_geographies: list[str]
    budget_label: str
    ideal_customer_profile: str
    preferred_company_sizes: list[str]
    preferred_sectors: list[str]
    offerings: list[str]
    goals: list[str]
    discovery_modes: list[str]
    opportunity_type_needed: str
    inclusion_keywords: list[str]
    exclusion_keywords: list[str]
    vendor_constraints: str
    supplier_constraints: str
    user_urls: list[str]
    targeting_model: TargetingModel


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: datetime | None = None


@dataclass(slots=True)
class DiscoveryDocument:
    adapter_name: str
    source_type: str
    discovery_mode: str
    url: str
    title: str
    snippet: str
    html: str
    status_code: int | None
    fetched_at: datetime


@dataclass(slots=True)
class ParsedDocument:
    url: str
    title: str
    meta_description: str
    visible_text: str
    headings: list[str]
    links: list[tuple[str, str]]
    emails: list[str]
    phone_numbers: list[str]
    likely_entity_name: str | None
    likely_location: str | None
    categories: list[str]
    ambiguous: bool


@dataclass(slots=True)
class ContactValidation:
    syntax_valid: bool
    mx_valid: bool
    smtp_code: int | None
    smtp_message: str | None

    @property
    def score(self) -> int:
        return (
            int(self.syntax_valid)
            + int(self.mx_valid)
            + int(self.smtp_code is not None and 200 <= self.smtp_code < 300)
        )

    @property
    def accepted(self) -> bool:
        return (
            self.syntax_valid
            and self.mx_valid
            and (self.smtp_code is None or 200 <= self.smtp_code < 300)
        )


@dataclass(slots=True)
class ContactPath:
    kind: str
    value: str
    label: str
    validation: ContactValidation | None = None
    source: str | None = None


@dataclass(slots=True)
class EnrichedEntity:
    discovery_mode: str
    source_type: str
    source_url: str
    entity_name: str
    entity_domain: str | None
    entity_website: str | None
    category: str
    description: str
    location: str
    company_size: str
    budget_signal: str
    trust_signals: list[str]
    timing_signals: list[str]
    accessibility_signals: list[str]
    matched_keywords: list[str]
    excluded: bool = False
    exclusion_reason: str | None = None
    decision_maker_name: str | None = None
    decision_maker_title: str | None = None
    decision_maker_email: str | None = None
    contact_paths: list[ContactPath] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OpportunityScore:
    fit: int
    relevance: int
    geography: int
    budget_compatibility: int
    intent: int
    accessibility: int
    trust: int
    timing: int
    expected_value: int
    priority_score: int
    confidence: int
    explanations: list[str]
    why_it_matters: str = ""
    next_action: str = ""


@dataclass(slots=True)
class Opportunity:
    priority_rank: int
    discovery_mode: str
    market_side: str
    entity_name: str
    entity_website: str | None
    entity_domain: str | None
    category: str
    location: str
    company_size: str
    budget_signal: str
    expected_value: str
    timing_signal: str
    decision_maker: str | None
    decision_maker_email: str | None
    email_validation: str
    contact_path: str
    source_type: str
    source_url: str
    priority_score: int
    confidence: int
    why_it_matters: str
    reasoning_summary: str
    next_action: str
    score: OpportunityScore

    def as_export_row(self) -> dict[str, Any]:
        return {
            "priority_rank": self.priority_rank,
            "priority_score": self.priority_score,
            "confidence": self.confidence,
            "discovery_mode": self.discovery_mode,
            "market_side": self.market_side,
            "entity_name": self.entity_name,
            "entity_website": self.entity_website,
            "entity_domain": self.entity_domain,
            "category": self.category,
            "location": self.location,
            "company_size": self.company_size,
            "budget_signal": self.budget_signal,
            "expected_value": self.expected_value,
            "timing_signal": self.timing_signal,
            "decision_maker": self.decision_maker,
            "decision_maker_email": self.decision_maker_email,
            "email_validation": self.email_validation,
            "contact_path": self.contact_path,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "why_it_matters": self.why_it_matters,
            "reasoning_summary": self.reasoning_summary,
            "next_action": self.next_action,
        }


@dataclass(slots=True)
class SkippedEntity:
    discovery_mode: str
    entity_name: str
    entity_website: str | None
    source_type: str
    source_url: str
    reason: str

    def as_export_row(self) -> dict[str, Any]:
        return {
            "discovery_mode": self.discovery_mode,
            "entity_name": self.entity_name,
            "entity_website": self.entity_website,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "reason": self.reason,
        }


@dataclass(slots=True)
class AuditRecord:
    run_id: str
    created_at: datetime
    business_name: str
    discovery_modes: list[str]
    opportunity_count: int
    skipped_count: int
    export_name: str
    export_uri: str | None
    log: list[str]


@dataclass(slots=True)
class DecisionRunResult:
    profile: BusinessProfile
    opportunities: list[Opportunity]
    skipped_entities: list[SkippedEntity]
    export_name: str
    export_bytes: bytes
    export_uri: str | None
    audit_record: AuditRecord
