from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from hackindia_leads.sources.base import SearchBackedSource


class DoraHacksSource(SearchBackedSource):
    domain = "dorahacks.io"
    query_format = 'site:dorahacks.io (hackathon OR bounty) "{keyword}"'

    @property
    def name(self) -> str:
        return "dorahacks"

    def accepts_event_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc.lower() != "dorahacks.io":
            return False
        path = parsed.path.rstrip("/")
        if not path.startswith("/hackathon"):
            return False
        if path == "/hackathon":
            return False
        return True

    def url_priority(self, url: str) -> int:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path.endswith("/detail"):
            return 0
        if parse_qs(parsed.query):
            return 20
        return 10

    def should_use_browser(self, url: str) -> bool:
        return True
