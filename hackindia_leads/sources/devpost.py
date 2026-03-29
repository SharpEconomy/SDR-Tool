from __future__ import annotations

from urllib.parse import urlparse

from hackindia_leads.sources.base import SearchBackedSource


class DevpostSource(SearchBackedSource):
    domain = "devpost.com"
    query_format = 'site:devpost.com ("hackathon" OR "hackathons") "{keyword}"'

    @property
    def name(self) -> str:
        return "devpost"

    def accepts_event_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host.endswith("devpost.com"):
            return False
        if host in {"devpost.com", "www.devpost.com", "info.devpost.com"}:
            return False
        return ".devpost.com" in host

    def url_priority(self, url: str) -> int:
        host = urlparse(url).netloc.lower()
        return 0 if host.count(".") >= 2 else 10

    def should_use_browser(self, url: str) -> bool:
        return True
