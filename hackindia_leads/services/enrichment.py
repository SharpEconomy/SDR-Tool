from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hackindia_leads.config import Settings
from hackindia_leads.models import ContactCandidate, Sponsor
from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient, SearchResult
from hackindia_leads.utils import extract_domain

DECISION_MAKER_HINTS = (
    "founder",
    "co-founder",
    "chief",
    "head",
    "director",
    "vp",
    "vice president",
    "partnership",
    "partnerships",
    "business development",
    "developer relations",
    "marketing",
    "community",
    "ecosystem",
    "growth",
    "sponsor",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
NAME_RE = re.compile(r"^[A-Z][A-Za-z'-]+(?: [A-Z][A-Za-z'-]+){1,2}$")
GENERIC_PREFIXES = {
    "admin",
    "careers",
    "contact",
    "hello",
    "help",
    "hi",
    "info",
    "legal",
    "marketing",
    "office",
    "partnerships",
    "privacy",
    "sales",
    "security",
    "sponsors",
    "support",
    "team",
}
COMMON_SITE_PATHS = ("", "/about", "/team", "/contact", "/company", "/leadership")


class ContactEnricher:
    def __init__(
        self,
        settings: Settings,
        fetcher: PageFetcher | None = None,
        search_client: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher or PageFetcher(settings)
        self.search_client = search_client or SearchClient(settings)

    def resolve_website(self, sponsor: Sponsor) -> str | None:
        candidates: list[str] = []
        direct = self._normalize_website(sponsor.website)
        if direct is not None:
            candidates.append(direct)

        results = self.search_client.search(
            f"{sponsor.name} official website", max_results=5
        )
        for item in results:
            website = self._normalize_website(item.url)
            domain = extract_domain(website)
            if website and domain and not self._is_bad_domain(domain):
                candidates.append(website)

        for website in candidates:
            if self.validate_website(website):
                return website

        return candidates[0] if candidates else None

    def resolve_domain(
        self, sponsor: Sponsor, website: str | None = None
    ) -> str | None:
        return extract_domain(website) or extract_domain(sponsor.website)

    def validate_website(self, website: str | None) -> bool:
        if not website:
            return False

        candidates = [website]
        parsed = urlparse(website if "://" in website else f"https://{website}")
        if not parsed.scheme:
            candidates.append(f"https://{website}")
        elif parsed.scheme == "https":
            candidates.append(f"http://{parsed.netloc}")

        for candidate in candidates:
            result = self.fetcher.fetch(candidate)
            if self._looks_like_live_website(result.status_code, result.text):
                return True
        return False

    def find_contact_candidates(
        self, sponsor: Sponsor, website: str | None, domain: str | None
    ) -> list[ContactCandidate]:
        if not domain:
            return []

        candidates: list[ContactCandidate] = []
        candidates.extend(self._find_website_email_candidates(website, domain))
        candidates.extend(self._find_search_candidates(sponsor, domain))

        deduped: dict[str, ContactCandidate] = {}
        for candidate in candidates:
            key = candidate.email.lower()
            current = deduped.get(key)
            if current is None or self._candidate_sort_key(candidate) > (
                self._candidate_sort_key(current)
            ):
                deduped[key] = candidate

        ordered = sorted(
            deduped.values(),
            key=self._candidate_sort_key,
            reverse=True,
        )
        return ordered[: self.settings.max_contacts_per_company * 4]

    def _find_website_email_candidates(
        self, website: str | None, domain: str
    ) -> list[ContactCandidate]:
        if not website:
            return []

        candidates: list[ContactCandidate] = []
        seen_emails: set[str] = set()
        for path in COMMON_SITE_PATHS:
            page_url = urljoin(f"{website}/", path.lstrip("/"))
            result = self.fetcher.fetch(page_url)
            if not self._looks_like_live_website(result.status_code, result.text):
                continue

            soup = BeautifulSoup(result.text, "html.parser")
            emails = set(EMAIL_RE.findall(soup.get_text(" ", strip=True)))
            for link in soup.select("a[href^='mailto:']"):
                href = link.get("href", "")
                emails.update(EMAIL_RE.findall(href))

            for email in emails:
                normalized = email.lower()
                if not normalized.endswith(f"@{domain}") or normalized in seen_emails:
                    continue
                seen_emails.add(normalized)
                local_part = normalized.split("@", 1)[0]
                candidates.append(
                    ContactCandidate(
                        full_name=self._display_name_from_local_part(local_part),
                        first_name=None,
                        last_name=None,
                        title="Website contact",
                        email=normalized,
                        source="website-email",
                        linkedin_url=None,
                        confidence=(
                            35 if self._looks_generic_local_part(local_part) else 75
                        ),
                    )
                )
        return candidates

    def _find_search_candidates(
        self, sponsor: Sponsor, domain: str
    ) -> list[ContactCandidate]:
        candidates: list[ContactCandidate] = []
        queries = [
            f'site:linkedin.com/in "{sponsor.name}" "founder"',
            f'site:linkedin.com/in "{sponsor.name}" "head of partnerships"',
            f'site:linkedin.com/in "{sponsor.name}" "business development"',
            f'site:linkedin.com/in "{sponsor.name}" "developer relations"',
        ]
        for query in queries:
            results = self.search_client.search(query, max_results=3)
            for item in results:
                candidates.extend(self._candidates_from_search_result(item, domain))
        return candidates

    def _candidates_from_search_result(
        self, result: SearchResult, domain: str
    ) -> list[ContactCandidate]:
        name, title = self._extract_name_and_title(result)
        if not name or self._title_score(title) == 0:
            return []

        first_name, last_name = self._split_name(name)
        if not first_name or not last_name:
            return []

        direct_emails = [
            email
            for email in EMAIL_RE.findall(f"{result.title} {result.snippet}")
            if email.lower().endswith(f"@{domain}")
        ]
        if direct_emails:
            return [
                ContactCandidate(
                    full_name=name,
                    first_name=first_name,
                    last_name=last_name,
                    title=title,
                    email=direct_emails[0].lower(),
                    source="public-search-email",
                    linkedin_url=(
                        result.url if "linkedin.com/in/" in result.url else None
                    ),
                    confidence=95,
                )
            ]

        base_confidence = min(95, 60 + self._title_score(title) * 8)
        guesses = self._guess_email_addresses(first_name, last_name, domain)
        return [
            ContactCandidate(
                full_name=name,
                first_name=first_name,
                last_name=last_name,
                title=title,
                email=email,
                source="public-search-pattern",
                linkedin_url=result.url if "linkedin.com/in/" in result.url else None,
                confidence=base_confidence - index,
            )
            for index, email in enumerate(guesses)
        ]

    def _extract_name_and_title(self, result: SearchResult) -> tuple[str | None, str]:
        cleaned_title = (
            result.title.replace("| LinkedIn", "").replace("- LinkedIn", "").strip()
        )
        parts = [part.strip() for part in cleaned_title.split(" - ") if part.strip()]
        if len(parts) >= 2 and NAME_RE.match(parts[0]):
            return parts[0], parts[1]

        snippet_parts = [
            part.strip() for part in result.snippet.split(" - ") if part.strip()
        ]
        if len(snippet_parts) >= 2 and NAME_RE.match(snippet_parts[0]):
            return snippet_parts[0], snippet_parts[1]

        return None, ""

    def _guess_email_addresses(
        self, first_name: str, last_name: str, domain: str
    ) -> list[str]:
        first = re.sub(r"[^a-z]", "", first_name.lower())
        last = re.sub(r"[^a-z]", "", last_name.lower())
        if not first or not last:
            return []

        patterns = [
            f"{first}.{last}@{domain}",
            f"{first}@{domain}",
            f"{first}{last}@{domain}",
            f"{first}_{last}@{domain}",
            f"{first}-{last}@{domain}",
            f"{first[0]}{last}@{domain}",
            f"{first}{last[0]}@{domain}",
            f"{last}.{first}@{domain}",
        ]
        return list(dict.fromkeys(patterns))

    def _split_name(self, full_name: str) -> tuple[str | None, str | None]:
        parts = [part for part in full_name.split() if part]
        if len(parts) < 2:
            return None, None
        return parts[0], parts[-1]

    def _candidate_sort_key(self, candidate: ContactCandidate) -> tuple[int, int, int]:
        source_bonus = 2 if candidate.source == "website-email" else 1
        confidence = candidate.confidence or 0
        return (source_bonus, self._title_score(candidate.title), confidence)

    def _display_name_from_local_part(self, local_part: str) -> str:
        cleaned = re.sub(r"[._-]+", " ", local_part).strip()
        return cleaned.title() or local_part

    def _looks_generic_local_part(self, local_part: str) -> bool:
        return local_part in GENERIC_PREFIXES

    def _normalize_website(self, website: str | None) -> str | None:
        if not website:
            return None
        parsed = urlparse(website if "://" in website else f"https://{website}")
        host = parsed.netloc.lower()
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        if self._is_bad_domain(host):
            return None
        return f"https://{host}"

    def _title_score(self, title: str) -> int:
        normalized = title.lower()
        return sum(1 for hint in DECISION_MAKER_HINTS if hint in normalized)

    def _looks_like_live_website(
        self, status_code: int | None, text: str | None = None
    ) -> bool:
        if status_code is None:
            return False
        if 200 <= status_code < 400:
            return True
        return status_code in {401, 403, 405} and bool(text is not None)

    def _is_bad_domain(self, domain: str) -> bool:
        blocked = (
            "linkedin.com",
            "twitter.com",
            "x.com",
            "instagram.com",
            "facebook.com",
            "youtube.com",
        )
        return any(domain.endswith(item) for item in blocked)
