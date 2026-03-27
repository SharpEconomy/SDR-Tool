from __future__ import annotations

import re
from urllib.parse import urljoin

from hackindia_leads.sources.base import SourceAdapter


class EthGlobalSource(SourceAdapter):
    @property
    def name(self) -> str:
        return "ethglobal"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        listing = self.fetcher.fetch("https://ethglobal.com/events")
        if not listing.text:
            return []
        matches = re.findall(r'href="(/events/[^"#?]+)"', listing.text)
        urls: list[str] = []
        blocked_tokens = ("pragma", "happy-hour", "cowork", "anniversary")
        for match in matches:
            if match == "/events":
                continue
            url = urljoin("https://ethglobal.com", match)
            slug = url.rsplit("/", 1)[-1].lower()
            if any(token in slug for token in blocked_tokens):
                continue
            if url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls
