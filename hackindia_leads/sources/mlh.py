from __future__ import annotations

import re
from datetime import date

from hackindia_leads.sources.base import SearchBackedSource


class MLHSource(SearchBackedSource):
    domain = "mlh"
    query_format = 'site:mlh.io OR site:events.mlh.io hackathon "{keyword}"'

    @property
    def name(self) -> str:
        return "mlh"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        base_urls: list[str] = []
        for season_year in self._season_years():
            listing = self.fetcher.fetch(f"https://mlh.io/seasons/{season_year}/events")
            if not listing.text:
                continue
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

    def _season_years(self) -> list[int]:
        current_year = date.today().year
        return [current_year, current_year + 1, current_year - 1]
