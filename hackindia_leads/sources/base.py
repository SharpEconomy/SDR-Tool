from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hackindia_leads.models import Event, Sponsor
from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.openai_client import OpenAIQualificationClient
from hackindia_leads.services.search import SearchClient
from hackindia_leads.utils import (
    clean_company_name,
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
NOISE_PATH_HINTS = (
    "/about",
    "/contact",
    "/privacy",
    "/terms",
    "/career",
    "/internships",
    "/forum",
    "/ambassadors",
    "/ecosystem",
    "/partners",
    "/companies",
    "/colleges",
    "/faq",
    "/news",
    "/register",
    "/login",
    "/sitemap",
)
SPONSOR_CTA_HINTS = (
    "partner with",
    "host a hackathon",
    "join thousands",
    "ready to partner",
    "contact",
    "register",
)
SPONSOR_NOISE_NAME_HINTS = (
    "find more",
    "view ",
    "managed by",
    "go to ",
    "privacy policy",
    "terms of service",
    "schedule",
    "rules",
    "beginner friendly",
    "low/no code",
)


class SourceAdapter(ABC):
    def __init__(self, fetcher: PageFetcher, search_client: SearchClient) -> None:
        self.fetcher = fetcher
        self.search_client = search_client
        self.openai_client = self._build_openai_client(fetcher)

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
        sponsors = self._adapt_sponsors_if_needed(url, soup, title, sponsors)
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
            section_nodes = self._section_nodes_for_heading(heading)
            if not section_nodes:
                continue
            is_prize_section = any(
                token in heading_text for token in ("prize", "bounty")
            )

            for node in section_nodes:
                for anchor in node.find_all("a", href=True):
                    anchor_text = self._anchor_company_name(anchor)
                    href = urljoin(url, anchor["href"])
                    domain = extract_domain(href)
                    if looks_like_company_name(anchor_text):
                        sponsors.append(
                            Sponsor(
                                name=clean_company_name(anchor_text),
                                website=href,
                                evidence=heading_text,
                            )
                        )
                    elif domain and domain not in PLATFORM_DOMAINS:
                        company = self._domain_to_company(domain)
                        sponsors.append(
                            Sponsor(
                                name=clean_company_name(company),
                                website=href,
                                evidence=heading_text,
                            )
                        )

            if is_prize_section:
                continue
            nearby_text = dedupe_keep_order(
                [
                    normalize_whitespace(item.get_text(" ", strip=True))
                    for node in section_nodes
                    for item in node.find_all(["li", "p", "span", "div"])
                ]
            )
            for item in nearby_text[:25]:
                if looks_like_company_name(item) and not is_likely_prize_label(item):
                    sponsors.append(
                        Sponsor(
                            name=clean_company_name(item),
                            evidence=heading_text,
                        )
                    )
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
        cleaned_sponsors = [
            Sponsor(
                name=clean_company_name(sponsor.name),
                website=sponsor.website,
                evidence=sponsor.evidence,
            )
            for sponsor in sponsors
            if clean_company_name(sponsor.name)
        ]
        return self._dedupe_sponsors(cleaned_sponsors)

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

    def _section_nodes_for_heading(self, heading) -> list:
        start = heading.parent or heading
        nodes = [start]
        sibling_count = 0
        for sibling in start.next_siblings:
            if sibling_count >= 3:
                break
            if getattr(sibling, "name", None) is None:
                continue
            if sibling.find(re.compile("^h[1-6]$")) is not None:
                break
            nodes.append(sibling)
            sibling_count += 1
        return nodes

    def _build_openai_client(
        self, fetcher: PageFetcher
    ) -> OpenAIQualificationClient | None:
        if hasattr(fetcher, "settings"):
            return OpenAIQualificationClient(fetcher.settings)
        return None

    def _adapt_sponsors_if_needed(
        self,
        url: str,
        soup: BeautifulSoup,
        title: str,
        sponsors: list[Sponsor],
    ) -> list[Sponsor]:
        if self.openai_client is None:
            return sponsors
        if not self.openai_client.is_configured():
            return sponsors
        if not self._needs_adaptive_sponsor_fallback(sponsors):
            return sponsors

        try:
            adapted = self._extract_sponsors_with_openai(url, soup, title)
        except Exception:
            return sponsors
        return adapted or sponsors

    def _needs_adaptive_sponsor_fallback(self, sponsors: list[Sponsor]) -> bool:
        if not sponsors:
            return True
        suspicious = sum(
            1 for sponsor in sponsors if self._looks_like_noise_sponsor(sponsor)
        )
        return suspicious >= max(1, (len(sponsors) + 1) // 2)

    def _looks_like_noise_sponsor(self, sponsor: Sponsor) -> bool:
        lowered_name = sponsor.name.lower()
        if any(token in lowered_name for token in SPONSOR_CTA_HINTS):
            return True
        if any(token in lowered_name for token in SPONSOR_NOISE_NAME_HINTS):
            return True
        website = sponsor.website or ""
        lowered_website = website.lower()
        domain = extract_domain(website)
        if domain in PLATFORM_DOMAINS:
            return True
        if any(token in lowered_website for token in NOISE_PATH_HINTS):
            return True
        return False

    def _extract_sponsors_with_openai(
        self,
        url: str,
        soup: BeautifulSoup,
        title: str,
    ) -> list[Sponsor]:
        headings = [
            normalize_whitespace(heading.get_text(" ", strip=True))
            for heading in soup.find_all(["h1", "h2", "h3", "h4"])
        ]
        headings = [heading for heading in headings if heading][:25]
        links = []
        for anchor in soup.find_all("a", href=True):
            text = normalize_whitespace(anchor.get_text(" ", strip=True))
            href = urljoin(url, anchor["href"])
            if not text and not href:
                continue
            links.append({"text": text, "href": href})
            if len(links) >= 60:
                break

        body_text = normalize_whitespace(soup.get_text(" ", strip=True))
        extracted = self.openai_client.extract_sponsors(
            {
                "event_url": url,
                "page_title": title,
                "headings": headings,
                "links": links,
                "body_excerpt": body_text[:6000],
            }
        )
        sponsors = [
            Sponsor(
                name=item["name"],
                website=item.get("website"),
                evidence=item.get("evidence"),
            )
            for item in extracted
        ]
        return self._dedupe_sponsors(sponsors)

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
