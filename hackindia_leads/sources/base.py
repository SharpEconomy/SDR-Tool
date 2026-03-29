from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hackindia_leads.models import Event, Sponsor
from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient
from hackindia_leads.utils import (
    dedupe_keep_order,
    extract_domain,
    is_likely_prize_label,
    looks_like_company_name,
    normalize_whitespace,
)

SPONSOR_HEADINGS = ("sponsor", "partner", "backed by", "prize", "bounty")
PLATFORM_DOMAINS = {
    "devpost.com",
    "ethglobal.com",
    "dorahacks.io",
    "mlh.io",
    "events.mlh.io",
    "organize.mlh.io",
}


class SourceAdapter(ABC):
    def __init__(self, fetcher: PageFetcher, search_client: SearchClient) -> None:
        self.fetcher = fetcher
        self.search_client = search_client

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        raise NotImplementedError

    def fetch_events(
        self,
        keywords: list[str],
        limit: int,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[Event]:
        events: list[Event] = []
        urls = self.discover_event_urls(keywords, limit)
        if progress_callback is not None:
            progress_callback(f"[{self.name}] discovered {len(urls)} event page(s)")
        for index, url in enumerate(urls, start=1):
            if progress_callback is not None:
                progress_callback(
                    f"[{self.name}] fetching event {index}/{len(urls)}: {url}"
                )
            result = self.fetcher.fetch(
                url, prefer_browser=self.should_use_browser(url)
            )
            if not result.text:
                if progress_callback is not None:
                    progress_callback(f"[{self.name}] skipped empty response: {url}")
                continue
            event = self.parse_event(url, result.text)
            if event is not None and event.sponsors:
                events.append(event)
                if progress_callback is not None:
                    progress_callback(
                        (
                            f"[{self.name}] parsed '{event.title}' with "
                            f"{len(event.sponsors)} sponsor(s)"
                        )
                    )
            elif progress_callback is not None:
                progress_callback(f"[{self.name}] no sponsors found on: {url}")
        return events

    def should_use_browser(self, url: str) -> bool:
        return False

    def parse_event(self, url: str, html: str) -> Event | None:
        soup = BeautifulSoup(html, "html.parser")
        title = normalize_whitespace(
            soup.title.get_text(" ", strip=True) if soup.title else url
        )
        summary = self._summary(soup)
        sponsors = self.extract_sponsors(url, soup, html)
        return Event(
            source=self.name, url=url, title=title, summary=summary, sponsors=sponsors
        )

    def extract_sponsors(
        self, url: str, soup: BeautifulSoup, html: str
    ) -> list[Sponsor]:
        sponsors = self.extract_sponsors_from_sections(url, soup)
        if sponsors:
            return sponsors
        return self.extract_sponsors_from_jsonish(html)

    def extract_sponsors_from_sections(
        self, url: str, soup: BeautifulSoup
    ) -> list[Sponsor]:
        sponsors: list[Sponsor] = []
        for heading in soup.find_all(re.compile("^h[1-6]$")):
            heading_text = normalize_whitespace(
                heading.get_text(" ", strip=True)
            ).lower()
            if not any(token in heading_text for token in SPONSOR_HEADINGS):
                continue
            parent = heading.parent
            if parent is None:
                continue
            is_prize_section = any(
                token in heading_text for token in ("prize", "bounty")
            )

            for anchor in parent.find_all("a", href=True):
                anchor_text = self._anchor_company_name(anchor)
                href = urljoin(url, anchor["href"])
                domain = extract_domain(href)
                if looks_like_company_name(anchor_text):
                    sponsors.append(
                        Sponsor(name=anchor_text, website=href, evidence=heading_text)
                    )
                elif domain and domain not in PLATFORM_DOMAINS:
                    company = self._domain_to_company(domain)
                    sponsors.append(
                        Sponsor(name=company, website=href, evidence=heading_text)
                    )

            if is_prize_section:
                continue
            nearby_text = dedupe_keep_order(
                [
                    normalize_whitespace(item.get_text(" ", strip=True))
                    for item in parent.find_all(["li", "p", "span", "div"])
                ]
            )
            for item in nearby_text[:25]:
                if looks_like_company_name(item) and not is_likely_prize_label(item):
                    sponsors.append(Sponsor(name=item, evidence=heading_text))
        return self._dedupe_sponsors(sponsors)

    def extract_sponsors_from_jsonish(self, html: str) -> list[Sponsor]:
        sponsors: list[Sponsor] = []
        pattern = re.compile(
            (
                r'\\"organization\\":\{\\"id\\":.*?\\"name\\":\\"(?P<name>[^"]+)\\"'
                r'.*?\\"website\\":\\"(?P<website>https?://[^"]+)\\"'
            ),
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            sponsors.append(
                Sponsor(
                    name=match.group("name"),
                    website=match.group("website"),
                    evidence="embedded-json",
                )
            )
        return self._dedupe_sponsors(sponsors)

    def _summary(self, soup: BeautifulSoup) -> str:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return normalize_whitespace(str(meta["content"]))
        paragraphs = [
            normalize_whitespace(p.get_text(" ", strip=True))
            for p in soup.find_all("p")
        ]
        paragraphs = [item for item in paragraphs if len(item) > 60]
        return paragraphs[0] if paragraphs else ""

    def _dedupe_sponsors(self, sponsors: list[Sponsor]) -> list[Sponsor]:
        seen: set[str] = set()
        output: list[Sponsor] = []
        for sponsor in sponsors:
            key = sponsor.name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(sponsor)
        return output

    def _anchor_company_name(self, anchor) -> str:
        candidates = [
            normalize_whitespace(anchor.get_text(" ", strip=True)),
            normalize_whitespace(str(anchor.get("aria-label", ""))),
            normalize_whitespace(str(anchor.get("title", ""))),
        ]
        for image in anchor.find_all("img"):
            candidates.append(normalize_whitespace(str(image.get("alt", ""))))
            candidates.append(normalize_whitespace(str(image.get("title", ""))))
        for candidate in candidates:
            if looks_like_company_name(candidate):
                return candidate
        return ""

    def _domain_to_company(self, domain: str) -> str:
        parts = [part for part in domain.split(".") if part]
        if len(parts) >= 2:
            root = parts[-2]
        else:
            root = parts[0]
        return root.replace("-", " ").title()


class SearchBackedSource(SourceAdapter):
    domain: str
    query_format: str

    def discover_event_urls(self, keywords: list[str], limit: int) -> list[str]:
        urls: list[str] = []
        per_keyword = max(3, limit)
        ranked_urls: list[tuple[int, str]] = []
        seen: set[str] = set()
        for keyword in keywords:
            query = self.query_format.format(keyword=keyword)
            for result in self.search_client.search(query, max_results=per_keyword):
                if not self.accepts_event_url(result.url):
                    continue
                if result.url in seen:
                    continue
                seen.add(result.url)
                ranked_urls.append((self.url_priority(result.url), result.url))

        ranked_urls.sort(key=lambda item: (item[0], item[1]))
        for _, url in ranked_urls:
            urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def accepts_event_url(self, url: str) -> bool:
        return self.domain in url

    def url_priority(self, url: str) -> int:
        return 100
