from __future__ import annotations

from hackindia_leads.sources.base import SearchBackedSource


class DoraHacksSource(SearchBackedSource):
    domain = "dorahacks.io"
    query_format = 'site:dorahacks.io (hackathon OR bounty) "{keyword}"'

    @property
    def name(self) -> str:
        return "dorahacks"

    def should_use_browser(self, url: str) -> bool:
        return True
