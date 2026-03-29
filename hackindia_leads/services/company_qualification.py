from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from hackindia_leads.config import Settings
from hackindia_leads.models import (
    CompanyQualification,
    ContactCandidate,
    ContactReview,
    EmailValidation,
    Event,
    Sponsor,
)
from hackindia_leads.services.openai_client import OpenAIQualificationClient
from hackindia_leads.services.search import SearchClient, SearchResult
from hackindia_leads.utils import extract_domain

AI_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "genai",
    "llm",
    "machine learning",
    "ml",
    "copilot",
    "agentic",
}
WEB3_KEYWORDS = {
    "web3",
    "blockchain",
    "crypto",
    "wallet",
    "token",
    "defi",
    "onchain",
    "smart contract",
}
TECH_KEYWORDS = {
    "api",
    "sdk",
    "platform",
    "developer platform",
    "cloud",
    "data",
    "infrastructure",
    "security",
    "saas",
    "software",
}
VISIBILITY_KEYWORDS = {
    "launch",
    "launched",
    "announce",
    "announced",
    "partnership",
    "partnerships",
    "ecosystem",
    "community",
    "growth",
    "expansion",
    "hiring",
    "sponsor",
    "hackathon",
}
FUNDING_KEYWORDS = {
    "raised",
    "funding",
    "series a",
    "series b",
    "series c",
    "seed round",
    "seed funding",
    "backed by",
    "investors",
    "valuation",
}
DEVELOPER_ADOPTION_KEYWORDS = {
    "api",
    "sdk",
    "developer",
    "developers",
    "devrel",
    "developer relations",
    "docs",
    "documentation",
    "integrations",
    "ecosystem",
    "community",
    "platform",
    "open source",
}
US_HINTS = {
    "united states",
    "usa",
    "us",
    "california",
    "new york",
    "texas",
    "delaware",
    "san francisco",
    "austin",
    "seattle",
    "boston",
}
INDIA_HINTS = {
    "india",
    "bengaluru",
    "bangalore",
    "mumbai",
    "delhi",
    "gurugram",
    "gurgaon",
    "hyderabad",
    "pune",
    "chennai",
    "noida",
}
PLATFORM_DOMAINS = {
    "devpost.com",
    "ethglobal.com",
    "dorahacks.io",
    "mlh.io",
    "events.mlh.io",
    "organize.mlh.io",
}


@dataclass(slots=True)
class _QualificationContext:
    sponsor: Sponsor
    event: Event
    website: str | None
    domain: str | None
    recent_decision_results: list[SearchResult]
    location_results: list[SearchResult]
    adoption_results: list[SearchResult]

    @property
    def combined_text(self) -> str:
        parts = [
            self.sponsor.name,
            self.website or "",
            self.domain or "",
            self.event.title,
            self.event.summary,
            self.sponsor.evidence or "",
        ]
        for result in self.all_results():
            parts.append(result.title)
            parts.append(result.snippet)
        return " ".join(part for part in parts if part).lower()

    def all_results(self) -> list[SearchResult]:
        deduped: dict[str, SearchResult] = {}
        for result in (
            self.recent_decision_results + self.location_results + self.adoption_results
        ):
            deduped.setdefault(result.url, result)
        return list(deduped.values())


@dataclass(slots=True)
class _RuleHints:
    company_segment: str
    segment_score: int
    company_location: str | None
    location_priority: str
    location_score: int
    developer_adoption_need: bool
    developer_adoption_score: int
    notes: list[str]


class CompanyQualifier:
    def __init__(
        self,
        settings: Settings,
        search_client: SearchClient | None = None,
        openai_client: OpenAIQualificationClient | None = None,
    ) -> None:
        self.settings = settings
        self.search_client = search_client or SearchClient(settings)
        self.openai_client = openai_client or OpenAIQualificationClient(settings)
        self._context_cache: dict[tuple[str, str], _QualificationContext] = {}
        self._cache: dict[tuple[str, str], CompanyQualification] = {}
        self._cache_lock = threading.Lock()

    def qualify(
        self,
        sponsor: Sponsor,
        event: Event,
        website: str | None,
        domain: str | None,
    ) -> CompanyQualification | None:
        if not self.is_enabled():
            return None

        cache_key = self._cache_key(sponsor, domain)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        context = self._get_context(cache_key, sponsor, event, website, domain)
        qualification = self._qualify_context(context)
        with self._cache_lock:
            self._cache[cache_key] = qualification
        return qualification

    def is_enabled(self) -> bool:
        return self.settings.qualification_enabled

    def review_contacts(
        self,
        sponsor: Sponsor,
        event: Event,
        website: str | None,
        domain: str | None,
        qualification: CompanyQualification,
        contacts: list[ContactCandidate],
        validations_by_email: dict[str, EmailValidation],
    ) -> dict[str, ContactReview]:
        if not contacts:
            return {}

        cache_key = self._cache_key(sponsor, domain)
        context = self._get_context(cache_key, sponsor, event, website, domain)
        if self._should_use_openai():
            try:
                return self._openai_contact_review(
                    context,
                    qualification,
                    contacts,
                    validations_by_email,
                )
            except Exception:
                return self._fallback_contact_review(
                    contacts,
                    validations_by_email,
                    "rule-based contact fallback used after OpenAI error",
                )

        if self.settings.use_openai_qualification:
            fallback_note = (
                "rule-based contact fallback used because OpenAI is unavailable"
            )
        else:
            fallback_note = (
                "rule-based contact fallback used because OpenAI is disabled"
            )
        return self._fallback_contact_review(
            contacts,
            validations_by_email,
            fallback_note,
        )

    def _build_context(
        self,
        sponsor: Sponsor,
        event: Event,
        website: str | None,
        domain: str | None,
    ) -> _QualificationContext:
        return _QualificationContext(
            sponsor=sponsor,
            event=event,
            website=website,
            domain=domain,
            recent_decision_results=self.search_client.search(
                (
                    f'"{sponsor.name}" raised funding OR series OR seed OR launch '
                    "OR partnership OR ecosystem OR community OR api OR sdk"
                ),
                max_results=6,
                recent_months=self.settings.qualification_recent_months,
            ),
            location_results=self.search_client.search(
                f'"{sponsor.name}" headquarters OR based in OR office',
                max_results=4,
            ),
            adoption_results=self.search_client.search(
                f'"{sponsor.name}" api sdk developers docs ecosystem open source',
                max_results=4,
            ),
        )

    def _get_context(
        self,
        cache_key: tuple[str, str],
        sponsor: Sponsor,
        event: Event,
        website: str | None,
        domain: str | None,
    ) -> _QualificationContext:
        with self._cache_lock:
            cached = self._context_cache.get(cache_key)
        if cached is not None:
            return cached

        context = self._build_context(sponsor, event, website, domain)
        with self._cache_lock:
            self._context_cache[cache_key] = context
        return context

    def _qualify_context(self, context: _QualificationContext) -> CompanyQualification:
        hints = self._build_rule_hints(context)
        if self._should_use_openai():
            try:
                qualification = self._openai_qualification(context, hints)
                return self._apply_sponsor_fit_override(
                    context,
                    hints,
                    qualification,
                )
            except Exception:
                qualification = self._fallback_qualification(
                    context,
                    hints,
                    "rule-based fallback used after OpenAI error",
                )
                return self._apply_sponsor_fit_override(
                    context,
                    hints,
                    qualification,
                )
        if self.settings.use_openai_qualification:
            fallback_note = "rule-based fallback used because OpenAI is unavailable"
        else:
            fallback_note = "rule-based fallback used because OpenAI is disabled"
        qualification = self._fallback_qualification(
            context,
            hints,
            fallback_note,
        )
        return self._apply_sponsor_fit_override(context, hints, qualification)

    def _build_rule_hints(self, context: _QualificationContext) -> _RuleHints:
        text = context.combined_text
        company_segment, segment_score = self._segment_signal(text)
        company_location, location_priority, location_score = self._location_signal(
            context
        )
        developer_adoption_need, developer_adoption_score = (
            self._developer_adoption_signal(text)
        )
        notes = self._hint_notes(
            company_segment,
            company_location,
            developer_adoption_need,
        )
        return _RuleHints(
            company_segment=company_segment,
            segment_score=segment_score,
            company_location=company_location,
            location_priority=location_priority,
            location_score=location_score,
            developer_adoption_need=developer_adoption_need,
            developer_adoption_score=developer_adoption_score,
            notes=notes,
        )

    def _openai_qualification(
        self,
        context: _QualificationContext,
        hints: _RuleHints,
    ) -> CompanyQualification:
        recent_evidence = [
            self._serialize_result(result) for result in context.recent_decision_results
        ]
        decision = self.openai_client.qualify(
            {
                "sponsor_name": context.sponsor.name,
                "sponsor_website": context.website,
                "sponsor_domain": context.domain,
                "event_title": context.event.title,
                "event_summary": context.event.summary,
                "rule_hints": {
                    "company_segment": hints.company_segment,
                    "company_location": hints.company_location,
                    "location_priority": hints.location_priority,
                    "developer_adoption_need": hints.developer_adoption_need,
                },
                "recent_data_policy": {
                    "decision_window_months": self.settings.qualification_recent_months,
                    "preferred_window_months": min(
                        self.settings.qualification_recent_months,
                        self.settings.qualification_preferred_recent_months,
                    ),
                },
                "recent_evidence": recent_evidence,
            }
        )

        notes = list(hints.notes)
        if decision["qualification_notes"]:
            notes.append(decision["qualification_notes"])
        elif not notes:
            notes.append("insufficient qualification signals")

        return CompanyQualification(
            company_segment=hints.company_segment,
            recently_funded=bool(decision["recently_funded"]),
            recent_funding_signal=decision["recent_funding_signal"],
            company_location=hints.company_location,
            location_priority=hints.location_priority,
            developer_adoption_need=hints.developer_adoption_need,
            market_visibility_need=bool(decision["market_visibility_need"]),
            qualification_notes="; ".join(notes),
            score=int(decision["score"]),
            accepted=bool(decision["accepted"]),
        )

    def _fallback_qualification(
        self,
        context: _QualificationContext,
        hints: _RuleHints,
        fallback_note: str,
    ) -> CompanyQualification:
        notes = list(hints.notes)
        recently_funded, recent_funding_signal, funding_score = (
            self._recent_funding_signal(context)
        )
        if recent_funding_signal:
            notes.append(recent_funding_signal)

        market_visibility_need, visibility_score = self._market_visibility_signal(
            context
        )
        if market_visibility_need:
            notes.append("market visibility signal")

        has_recent_evidence = bool(context.recent_decision_results)
        score = min(
            100,
            (
                hints.segment_score
                + hints.location_score
                + hints.developer_adoption_score
                + funding_score
                + visibility_score
            )
            * 10,
        )
        accepted = bool(
            has_recent_evidence
            and hints.company_segment != "Other"
            and score >= 60
            and (recently_funded or market_visibility_need)
        )
        if not notes:
            notes.append("insufficient qualification signals")
        notes.append(fallback_note)

        return CompanyQualification(
            company_segment=hints.company_segment,
            recently_funded=recently_funded,
            recent_funding_signal=recent_funding_signal,
            company_location=hints.company_location,
            location_priority=hints.location_priority,
            developer_adoption_need=hints.developer_adoption_need,
            market_visibility_need=market_visibility_need,
            qualification_notes="; ".join(notes),
            score=score,
            accepted=accepted,
        )

    def _openai_contact_review(
        self,
        context: _QualificationContext,
        qualification: CompanyQualification,
        contacts: list[ContactCandidate],
        validations_by_email: dict[str, EmailValidation],
    ) -> dict[str, ContactReview]:
        response = self.openai_client.review_contacts(
            {
                "sponsor_name": context.sponsor.name,
                "sponsor_website": context.website,
                "sponsor_domain": context.domain,
                "event_title": context.event.title,
                "event_summary": context.event.summary,
                "sponsor_review": {
                    "accepted": qualification.accepted,
                    "score": qualification.score,
                    "company_segment": qualification.company_segment,
                    "company_location": qualification.company_location,
                    "location_priority": qualification.location_priority,
                    "developer_adoption_need": qualification.developer_adoption_need,
                    "market_visibility_need": qualification.market_visibility_need,
                    "qualification_notes": qualification.qualification_notes,
                },
                "recent_evidence": [
                    self._serialize_result(result)
                    for result in context.recent_decision_results
                ],
                "max_selected": self.settings.max_contacts_per_company,
                "contacts": [
                    {
                        "full_name": contact.full_name,
                        "title": contact.title,
                        "email": contact.email,
                        "source": contact.source,
                        "linkedin_url": contact.linkedin_url,
                        "confidence": contact.confidence,
                        "email_validation": self._serialize_validation(
                            validations_by_email[contact.email]
                        ),
                    }
                    for contact in contacts
                ],
            }
        )

        selection_notes = response.get("selection_notes", "")
        reviews: dict[str, ContactReview] = {}
        for item in response.get("contacts", []):
            email = str(item.get("email", "")).strip().lower()
            if not email:
                continue
            note = str(item.get("reason", "")).strip()
            if selection_notes:
                note = f"{note}; {selection_notes}" if note else selection_notes
            reviews[email] = ContactReview(
                accepted=bool(item.get("accepted")),
                score=max(0, min(int(item.get("score", 0)), 100)),
                notes=note or None,
            )

        default_note = (
            selection_notes or "contact rejected because OpenAI returned no decision"
        )
        for contact in contacts:
            reviews.setdefault(
                contact.email.lower(),
                ContactReview(
                    accepted=False,
                    score=0,
                    notes=default_note,
                ),
            )
        return reviews

    def _fallback_contact_review(
        self,
        contacts: list[ContactCandidate],
        validations_by_email: dict[str, EmailValidation],
        fallback_note: str,
    ) -> dict[str, ContactReview]:
        ordered_contacts = sorted(
            contacts,
            key=self._contact_sort_key,
            reverse=True,
        )
        accepted_emails = {
            contact.email.lower()
            for contact in ordered_contacts[: self.settings.max_contacts_per_company]
        }
        reviews: dict[str, ContactReview] = {}
        for contact in contacts:
            email = contact.email.lower()
            validation = validations_by_email[contact.email]
            base_score = max(0, min((contact.confidence or 0), 100))
            if validation.accepted:
                base_score = min(100, base_score + 10)
            if contact.linkedin_url:
                base_score = min(100, base_score + 5)
            reviews[email] = ContactReview(
                accepted=email in accepted_emails,
                score=base_score,
                notes=fallback_note,
            )
        return reviews

    def _segment_signal(self, text: str) -> tuple[str, int]:
        if self._contains_any(text, WEB3_KEYWORDS):
            return "Web3", 3
        if self._contains_any(text, AI_KEYWORDS):
            return "AI", 3
        if self._contains_any(text, TECH_KEYWORDS):
            return "Tech", 2
        return "Other", 0

    def _location_signal(
        self, context: _QualificationContext
    ) -> tuple[str | None, str, int]:
        for result in context.location_results + context.all_results():
            content = f"{result.title} {result.snippet}".lower()
            if self._contains_any(content, INDIA_HINTS):
                return "India", "India", 2
            if self._contains_any(content, US_HINTS):
                return "United States", "US", 2
        if context.website or context.domain:
            return "Global", "Global", 1
        return None, "Unknown", 0

    def _developer_adoption_signal(self, text: str) -> tuple[bool, int]:
        return self._keyword_score(text, DEVELOPER_ADOPTION_KEYWORDS, threshold=2)

    def _recent_funding_signal(
        self,
        context: _QualificationContext,
    ) -> tuple[bool, str | None, int]:
        for result in context.recent_decision_results:
            content = f"{result.title} {result.snippet}".lower()
            if self._contains_any(content, FUNDING_KEYWORDS):
                return True, self._best_signal_text(result), 3
        return False, None, 0

    def _market_visibility_signal(
        self,
        context: _QualificationContext,
    ) -> tuple[bool, int]:
        recent_text = " ".join(
            f"{result.title} {result.snippet}"
            for result in context.recent_decision_results
        ).lower()
        return self._keyword_score(recent_text, VISIBILITY_KEYWORDS, threshold=2)

    def _hint_notes(
        self,
        company_segment: str,
        company_location: str | None,
        developer_adoption_need: bool,
    ) -> list[str]:
        notes: list[str] = []
        if company_segment != "Other":
            notes.append(f"{company_segment} fit")
        if company_location:
            notes.append(f"location: {company_location}")
        if developer_adoption_need:
            notes.append("developer adoption signal")
        return notes

    def _keyword_score(
        self,
        text: str,
        keywords: set[str],
        *,
        threshold: int,
    ) -> tuple[bool, int]:
        matches = sum(1 for keyword in keywords if keyword in text)
        if matches >= threshold:
            return True, 2
        if matches == 1:
            return True, 1
        return False, 0

    def _best_signal_text(self, result: SearchResult) -> str:
        return (result.title or result.snippet or result.url).strip() or result.url

    def _apply_sponsor_fit_override(
        self,
        context: _QualificationContext,
        hints: _RuleHints,
        qualification: CompanyQualification,
    ) -> CompanyQualification:
        if qualification.accepted:
            return qualification
        domain = extract_domain(context.website) or context.domain
        if not domain or domain in PLATFORM_DOMAINS:
            return qualification
        if hints.company_segment == "Other":
            return qualification
        if not self._sponsor_matches_domain(context.sponsor.name, domain):
            return qualification

        notes = qualification.qualification_notes or ""
        override_note = "accepted by sponsor-domain fit override"
        merged_notes = f"{notes}; {override_note}" if notes else override_note
        return CompanyQualification(
            company_segment=qualification.company_segment,
            recently_funded=qualification.recently_funded,
            recent_funding_signal=qualification.recent_funding_signal,
            company_location=qualification.company_location,
            location_priority=qualification.location_priority,
            developer_adoption_need=qualification.developer_adoption_need,
            market_visibility_need=qualification.market_visibility_need,
            qualification_notes=merged_notes,
            score=max(qualification.score, 60),
            accepted=True,
        )

    def _sponsor_matches_domain(self, sponsor_name: str, domain: str) -> bool:
        sponsor_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", sponsor_name.lower())
            if len(token) > 1
            and token not in {"labs", "foundation", "network", "protocol", "logo"}
        }
        if not sponsor_tokens:
            return False
        domain_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", domain.lower())
            if len(token) > 1
        }
        return any(token in domain_tokens for token in sponsor_tokens)

    def _should_use_openai(self) -> bool:
        return (
            self.settings.use_openai_qualification
            and self.openai_client.is_configured()
        )

    def _serialize_result(self, result: SearchResult) -> dict[str, Any]:
        return {
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet,
            "published_at": (
                result.published_at.isoformat()
                if result.published_at is not None
                else None
            ),
        }

    def _contains_any(self, text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _cache_key(self, sponsor: Sponsor, domain: str | None) -> tuple[str, str]:
        company = sponsor.name.strip().lower()
        normalized_domain = (domain or "").strip().lower()
        return company, normalized_domain

    def _serialize_validation(self, validation: EmailValidation) -> dict[str, Any]:
        return {
            "syntax_valid": validation.syntax_valid,
            "mx_valid": validation.mx_valid,
            "smtp_code": validation.smtp_code,
            "smtp_message": validation.smtp_message,
            "score": validation.score,
            "accepted": validation.accepted,
        }

    def _contact_sort_key(self, contact: ContactCandidate) -> tuple[int, int, int]:
        source_rank = 2 if contact.source == "public-search-email" else 1
        linkedin_rank = 1 if contact.linkedin_url else 0
        return (
            source_rank,
            linkedin_rank,
            contact.confidence or 0,
        )
