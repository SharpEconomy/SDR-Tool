from __future__ import annotations

from urllib.parse import urlparse

from hackindia_leads.sources.base import SearchBackedSource


class DevpostSource(SearchBackedSource):
    domain = "devpost.com"
    query_format = 'site:devpost.com ("hackathon" OR "hackathons") "{keyword}"'

    @property
    def name(self) -> str:
        return "devpost"

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        urls: list[str] = []
        per_keyword = max(3, limit)
        ranked_urls: list[tuple[int, str]] = []
        seen: set[str] = set()
        for keyword in keywords:
            query = self.query_format.format(keyword=keyword)
            for result in self.search_client.search(query, max_results=per_keyword):
                normalized = self._normalize_event_url(result.url)
                if not self.accepts_event_url(normalized):
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                ranked_urls.append((self.url_priority(normalized), normalized))

        ranked_urls.sort(key=lambda item: (item[0], item[1]))
        for _, url in ranked_urls:
            urls.append(url)
            if len(urls) >= limit:
                break
        return urls

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

    def _normalize_event_url(self, url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        return f"{scheme}://{parsed.netloc}/"
