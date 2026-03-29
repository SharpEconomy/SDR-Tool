from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hackindia_leads.sources.base import NOISE_PATH_HINTS, SourceAdapter

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
