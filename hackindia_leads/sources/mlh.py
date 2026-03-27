from __future__ import annotations

import re

from hackindia_leads.sources.base import SearchBackedSource


class MLHSource(SearchBackedSource):
    domain = "mlh"
    query_format = 'site:mlh.io OR site:events.mlh.io hackathon "{keyword}"'

    @property
    def name(self) -> str:
        return "mlh"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        base_urls: list[str] = []
        listing = self.fetcher.fetch("https://mlh.io/seasons/2026/events")
        if listing.text:
            base_urls.extend(
                re.findall(
                    r'href="(https://(?:events|organize)\.mlh\.io/events/[^"]+)"',
                    listing.text,
                )
            )
        deduped: list[str] = []
        for url in base_urls:
            if url not in deduped:
                deduped.append(url)
        if len(deduped) >= limit:
            return deduped[:limit]
        for url in super().discover_event_urls(keywords, limit):
            if url not in deduped:
                deduped.append(url)
            if len(deduped) >= limit:
                break
        return deduped

    def should_use_browser(self, url: str) -> bool:
        return True
