from __future__ import annotations

from hackindia_leads.sources.base import SearchBackedSource


class DevpostSource(SearchBackedSource):
    domain = "devpost.com"
    query_format = 'site:devpost.com ("hackathon" OR "hackathons") "{keyword}"'

    @property
    def name(self) -> str:
        return "devpost"

    def should_use_browser(self, url: str) -> bool:
        return True
