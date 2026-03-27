from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime

from hackindia_leads.config import Settings
from hackindia_leads.models import CompanyQualification, Event, Sponsor
from hackindia_leads.services.search import SearchClient, SearchResult

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
YEAR_RE = re.compile(r"\b(20\d{2})\b")


@dataclass(slots=True)
class _QualificationContext:
    sponsor: Sponsor
    event: Event
    website: str | None
    domain: str | None
    funding_results: list[SearchResult]
    location_results: list[SearchResult]
    adoption_results: list[SearchResult]
    visibility_results: list[SearchResult]

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
            self.funding_results
            + self.location_results
            + self.adoption_results
            + self.visibility_results
        ):
            deduped.setdefault(result.url, result)
        return list(deduped.values())


class CompanyQualifier:
    def __init__(
        self,
        settings: Settings,
        search_client: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.search_client = search_client or SearchClient(settings)
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

        context = self._build_context(sponsor, event, website, domain)
        qualification = self._score_context(context)
        with self._cache_lock:
            self._cache[cache_key] = qualification
        return qualification

    def is_enabled(self) -> bool:
        return self.settings.qualification_enabled

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
            funding_results=self.search_client.search(
                f'"{sponsor.name}" raised funding OR series OR seed',
                max_results=4,
            ),
            location_results=self.search_client.search(
                f'"{sponsor.name}" headquarters OR based in',
                max_results=4,
            ),
            adoption_results=self.search_client.search(
                f'"{sponsor.name}" api sdk developers docs ecosystem',
                max_results=4,
            ),
            visibility_results=self.search_client.search(
                f'"{sponsor.name}" launch partnerships community growth',
                max_results=4,
            ),
        )

    def _score_context(self, context: _QualificationContext) -> CompanyQualification:
        notes: list[str] = []
        text = context.combined_text

        company_segment, segment_score = self._segment_signal(text)
        if company_segment != "Other":
            notes.append(f"{company_segment} fit")

        recently_funded, funding_signal, funding_score = self._funding_signal(context)
        if funding_signal:
            notes.append(funding_signal)

        company_location, location_priority, location_score = self._location_signal(
            context
        )
        if company_location:
            notes.append(f"location: {company_location}")

        developer_adoption_need, developer_score = self._keyword_score(
            text,
            DEVELOPER_ADOPTION_KEYWORDS,
            threshold=2,
        )
        if developer_adoption_need:
            notes.append("developer adoption signal")

        market_visibility_need, visibility_score = self._visibility_signal(context)
        if market_visibility_need:
            notes.append("market visibility signal")

        score = (
            segment_score
            + funding_score
            + location_score
            + developer_score
            + visibility_score
        )
        accepted = bool(
            company_segment != "Other"
            and score >= 6
            and (developer_adoption_need or market_visibility_need)
        )
        if not notes:
            notes.append("insufficient qualification signals")

        return CompanyQualification(
            company_segment=company_segment,
            recently_funded=recently_funded,
            recent_funding_signal=funding_signal,
            company_location=company_location,
            location_priority=location_priority,
            developer_adoption_need=developer_adoption_need,
            market_visibility_need=market_visibility_need,
            qualification_notes="; ".join(notes),
            score=score,
            accepted=accepted,
        )

    def _segment_signal(self, text: str) -> tuple[str, int]:
        if self._contains_any(text, WEB3_KEYWORDS):
            return "Web3", 3
        if self._contains_any(text, AI_KEYWORDS):
            return "AI", 3
        if self._contains_any(text, TECH_KEYWORDS):
            return "Tech", 2
        return "Other", 0

    def _funding_signal(
        self, context: _QualificationContext
    ) -> tuple[bool, str | None, int]:
        recent_years = {datetime.now().year - offset for offset in range(0, 3)}
        for result in context.funding_results:
            content = f"{result.title} {result.snippet}".lower()
            if not self._contains_any(content, FUNDING_KEYWORDS):
                continue
            years = {int(match.group(1)) for match in YEAR_RE.finditer(content)}
            if years & recent_years:
                return True, self._best_signal_text(result), 3
            return True, self._best_signal_text(result), 2
        return False, None, 0

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

    def _visibility_signal(self, context: _QualificationContext) -> tuple[bool, int]:
        text = context.combined_text
        matched, keyword_score = self._keyword_score(
            text,
            VISIBILITY_KEYWORDS,
            threshold=2,
        )
        if matched:
            return True, keyword_score
        if context.event.source and context.sponsor.evidence:
            return True, 1
        return False, 0

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

    def _contains_any(self, text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _best_signal_text(self, result: SearchResult) -> str:
        return (result.title or result.snippet or result.url).strip() or result.url

    def _cache_key(self, sponsor: Sponsor, domain: str | None) -> tuple[str, str]:
        company = sponsor.name.strip().lower()
        normalized_domain = (domain or "").strip().lower()
        return company, normalized_domain
