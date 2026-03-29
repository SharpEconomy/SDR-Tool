from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from hackindia_leads.sources.base import SourceAdapter


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
    def __init__(self, fetcher, search_client, urls: list[str]) -> None:
        super().__init__(fetcher, search_client)
        self._urls = normalize_custom_urls(urls)

    @property
    def name(self) -> str:
        return "custom"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        return self._urls[:limit]
