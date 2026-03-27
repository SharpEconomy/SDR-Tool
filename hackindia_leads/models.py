from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PUBLIC_LEAD_COLUMNS = [
    "source",
    "event_name",
    "event_url",
    "sponsor_company",
    "sponsor_website",
    "company_segment",
    "recently_funded",
    "company_location",
    "developer_adoption_need",
    "market_visibility_need",
    "decision_maker_name",
    "decision_maker_title",
    "decision_maker_email",
    "linkedin_url",
]


@dataclass(slots=True)
class Sponsor:
    name: str
    website: str | None = None
    evidence: str | None = None


@dataclass(slots=True)
class Event:
    source: str
    url: str
    title: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    sponsors: list[Sponsor] = field(default_factory=list)


@dataclass(slots=True)
class ContactCandidate:
    full_name: str
    first_name: str | None
    last_name: str | None
    title: str
    email: str
    source: str
    linkedin_url: str | None = None
    confidence: int | None = None


@dataclass(slots=True)
class EmailValidation:
    syntax_valid: bool
    mx_valid: bool
    smtp_code: int | None
    smtp_message: str | None

    @property
    def score(self) -> int:
        score = 0
        if self.syntax_valid:
            score += 1
        if self.mx_valid:
            score += 1
        if self.smtp_code and 200 <= self.smtp_code < 300:
            score += 1
        return score

    @property
    def accepted(self) -> bool:
        return (
            self.syntax_valid
            and self.mx_valid
            and (self.smtp_code is None or 200 <= self.smtp_code < 300)
        )


@dataclass(slots=True)
class CompanyQualification:
    company_segment: str | None
    recently_funded: bool | None
    recent_funding_signal: str | None
    company_location: str | None
    location_priority: str | None
    developer_adoption_need: bool | None
    market_visibility_need: bool | None
    qualification_notes: str | None
    score: int
    accepted: bool


@dataclass(slots=True)
class Lead:
    source: str
    event_name: str
    event_url: str
    sponsor_company: str
    sponsor_website: str | None
    sponsor_domain: str | None
    company_segment: str | None
    recently_funded: bool | None
    recent_funding_signal: str | None
    company_location: str | None
    location_priority: str | None
    developer_adoption_need: bool | None
    market_visibility_need: bool | None
    decision_maker_name: str | None
    decision_maker_title: str | None
    decision_maker_email: str | None
    contact_source: str | None
    linkedin_url: str | None
    email_smtp_code: int | None
    email_score: int
    email_accepted: bool
    evidence: str | None
    qualification_notes: str | None
    qualification_score: int
    qualification_accepted: bool

    def as_row(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "event_name": self.event_name,
            "event_url": self.event_url,
            "sponsor_company": self.sponsor_company,
            "sponsor_website": self.sponsor_website,
            "sponsor_domain": self.sponsor_domain,
            "company_segment": self.company_segment,
            "recently_funded": self.recently_funded,
            "recent_funding_signal": self.recent_funding_signal,
            "company_location": self.company_location,
            "location_priority": self.location_priority,
            "developer_adoption_need": self.developer_adoption_need,
            "market_visibility_need": self.market_visibility_need,
            "decision_maker_name": self.decision_maker_name,
            "decision_maker_title": self.decision_maker_title,
            "decision_maker_email": self.decision_maker_email,
            "contact_source": self.contact_source,
            "linkedin_url": self.linkedin_url,
            "email_smtp_code": self.email_smtp_code,
            "email_score": self.email_score,
            "email_accepted": self.email_accepted,
            "evidence": self.evidence,
            "qualification_notes": self.qualification_notes,
            "qualification_score": self.qualification_score,
            "qualification_accepted": self.qualification_accepted,
        }

    def as_export_row(self) -> dict[str, Any]:
        row = self.as_row()
        return {column: row[column] for column in PUBLIC_LEAD_COLUMNS}
