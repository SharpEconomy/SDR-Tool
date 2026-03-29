from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hackindia_leads.models import Event, Sponsor
from hackindia_leads.services.openai_client import OpenAIQualificationClient
from hackindia_leads.sources.base import SourceAdapter
from hackindia_leads.utils import normalize_whitespace

COMMON_EVENT_INDEX_PATHS = (
    "/hackathons",
    "/events",
    "/challenges",
    "/buildathons",
    "/schedule",
)
EVENT_URL_HINTS = (
    "/20",
    "hackathon",
    "hackathons",
    "buildathon",
    "challenge",
    "summit",
    "sprint",
    "cup",
)
NOISE_PATH_HINTS = (
    "/about",
    "/contact",
    "/privacy",
    "/terms",
    "/career",
    "/internships",
    "/forum",
    "/ambassadors",
    "/ecosystem",
    "/partners",
    "/companies",
    "/colleges",
    "/faq",
    "/news",
    "/register",
    "/login",
    "/sitemap",
)
SPONSOR_CTA_HINTS = (
    "partner with",
    "host a hackathon",
    "join thousands",
    "ready to partner",
    "contact",
    "register",
)


def normalize_custom_urls(urls: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        candidate = url.strip()
        if not candidate:
            continue
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urlparse(candidate)
        if not parsed.netloc or "." not in parsed.netloc:
            continue
        cleaned = f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path or ''}"
        if parsed.query:
            cleaned = f"{cleaned}?{parsed.query}"
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


class CustomWebsiteSource(SourceAdapter):
    def __init__(
        self, fetcher, search_client, urls: list[str], openai_client=None
    ) -> None:
        super().__init__(fetcher, search_client)
        self._urls = normalize_custom_urls(urls)
        if openai_client is not None:
            self.openai_client = openai_client
        elif hasattr(fetcher, "settings"):
            self.openai_client = OpenAIQualificationClient(fetcher.settings)
        else:
            self.openai_client = None

    @property
    def name(self) -> str:
        return "custom"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        discovered: list[str] = []
        seen: set[str] = set()

        for seed_url in self._urls:
            for candidate in self._candidate_urls_for_seed(seed_url):
                if candidate in seen:
                    continue
                seen.add(candidate)
                discovered.append(candidate)
                if len(discovered) >= limit:
                    return discovered

        return discovered[:limit]

    def parse_event(self, url: str, html: str) -> Event | None:
        event = super().parse_event(url, html)
        if event is None or self.openai_client is None:
            return event
        if not self.openai_client.is_configured():
            return event
        if event.sponsors and not self._needs_openai_sponsor_fallback(event.sponsors):
            return event

        try:
            sponsors = self._extract_sponsors_with_openai(url, html, event.title)
        except Exception:
            return event
        if not sponsors:
            return event
        event.sponsors = sponsors
        return event

    def _candidate_urls_for_seed(self, seed_url: str) -> list[str]:
        pages_to_scan = [seed_url]
        parsed_seed = urlparse(seed_url)
        base_url = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
        if parsed_seed.path in {"", "/"}:
            for path in COMMON_EVENT_INDEX_PATHS:
                pages_to_scan.append(urljoin(base_url, path))

        event_links: list[str] = []
        for page_url in pages_to_scan:
            event_links.extend(self._discover_event_links(page_url, parsed_seed.netloc))

        ranked_links = sorted(
            {url for url in event_links if self._looks_like_event_url(url)},
            key=self._event_url_sort_key,
        )
        if ranked_links:
            return ranked_links
        return [seed_url]

    def _discover_event_links(self, page_url: str, host: str) -> list[str]:
        result = self.fetcher.fetch(page_url, prefer_browser=True)
        if not result.text:
            return []

        soup = BeautifulSoup(result.text, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, anchor["href"])
            parsed = urlparse(href)
            if parsed.netloc.lower() != host.lower():
                continue
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                normalized = f"{normalized}?{parsed.query}"
            links.append(normalized)
        return links

    def _looks_like_event_url(self, url: str) -> bool:
        lowered = url.lower()
        if any(token in lowered for token in NOISE_PATH_HINTS):
            return False
        path = urlparse(url).path.rstrip("/") or "/"
        if path in COMMON_EVENT_INDEX_PATHS:
            return False
        return any(token in lowered for token in EVENT_URL_HINTS)

    def _event_url_sort_key(self, url: str) -> tuple[int, int, str]:
        lowered = url.lower()
        year_bonus = 0 if "/20" in lowered else 1
        hackathon_bonus = 0 if "hackathon" in lowered else 1
        depth = -len([part for part in urlparse(url).path.split("/") if part])
        return (year_bonus, hackathon_bonus, depth, lowered)

    def _needs_openai_sponsor_fallback(self, sponsors: list[Sponsor]) -> bool:
        if not sponsors:
            return True
        return all(
            any(token in sponsor.name.lower() for token in SPONSOR_CTA_HINTS)
            or (
                sponsor.website is not None
                and any(token in sponsor.website.lower() for token in NOISE_PATH_HINTS)
            )
            for sponsor in sponsors
        )

    def _extract_sponsors_with_openai(
        self,
        url: str,
        html: str,
        title: str,
    ) -> list[Sponsor]:
        soup = BeautifulSoup(html, "html.parser")
        headings = [
            normalize_whitespace(heading.get_text(" ", strip=True))
            for heading in soup.find_all(["h1", "h2", "h3", "h4"])
        ]
        headings = [heading for heading in headings if heading][:25]
        links = []
        for anchor in soup.find_all("a", href=True):
            text = normalize_whitespace(anchor.get_text(" ", strip=True))
            href = urljoin(url, anchor["href"])
            if not text and not href:
                continue
            links.append({"text": text, "href": href})
            if len(links) >= 60:
                break

        body_text = normalize_whitespace(soup.get_text(" ", strip=True))
        payload = {
            "event_url": url,
            "page_title": title,
            "headings": headings,
            "links": links,
            "body_excerpt": body_text[:6000],
        }
        extracted = self.openai_client.extract_sponsors(payload)
        sponsors = [
            Sponsor(
                name=item["name"],
                website=item.get("website"),
                evidence=item.get("evidence"),
            )
            for item in extracted
        ]
        return self._dedupe_sponsors(sponsors)
