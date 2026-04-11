from __future__ import annotations

import re

from bs4 import BeautifulSoup

from growth_engine.models import DiscoveryDocument, ParsedDocument
from growth_engine.utils import extract_domain, normalize_whitespace

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s()-]{7,}\d)")
LOCATION_HINTS = (
    "india",
    "mumbai",
    "delhi",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "pune",
    "chennai",
    "gurugram",
    "noida",
)

CATEGORY_KEYWORDS = {
    "software": ["software", "saas", "platform", "crm", "erp"],
    "manufacturing": ["manufacturer", "factory", "plant", "industrial"],
    "logistics": ["logistics", "warehouse", "distribution", "freight"],
    "services": ["consulting", "services", "agency", "implementation"],
    "procurement": ["rfq", "tender", "procurement", "bid"],
}


class HtmlParsingService:
    def parse(self, document: DiscoveryDocument) -> ParsedDocument:
        soup = BeautifulSoup(document.html or "", "html.parser")
        title = normalize_whitespace(
            soup.title.string if soup.title else document.title
        )
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta",
            attrs={"property": "og:description"},
        )
        meta_description = normalize_whitespace(meta.get("content", "")) if meta else ""
        headings = [
            normalize_whitespace(node.get_text(" ", strip=True))
            for node in soup.select("h1, h2, h3")
            if normalize_whitespace(node.get_text(" ", strip=True))
        ][:12]
        visible_text = normalize_whitespace(soup.get_text(" ", strip=True))[:8000]
        emails = list(
            dict.fromkeys(email.lower() for email in EMAIL_RE.findall(visible_text))
        )
        phones = list(dict.fromkeys(PHONE_RE.findall(visible_text)))
        links = []
        for anchor in soup.select("a[href]"):
            href = normalize_whitespace(anchor.get("href", ""))
            label = normalize_whitespace(anchor.get_text(" ", strip=True))
            if href:
                links.append((label, href))
        likely_entity_name = self._likely_entity_name(title, headings, document.url)
        likely_location = self._likely_location(
            f"{title} {meta_description} {visible_text}"
        )
        categories = self._categories(visible_text, title, meta_description)
        ambiguous = len(visible_text) < 250 or not likely_entity_name or not categories
        return ParsedDocument(
            url=document.url,
            title=title or document.title,
            meta_description=meta_description,
            visible_text=visible_text,
            headings=headings,
            links=links,
            emails=emails,
            phone_numbers=phones,
            likely_entity_name=likely_entity_name,
            likely_location=likely_location,
            categories=categories,
            ambiguous=ambiguous,
        )

    def _likely_entity_name(
        self,
        title: str,
        headings: list[str],
        url: str,
    ) -> str | None:
        candidates = [title, *headings[:2]]
        for candidate in candidates:
            parts = [
                normalize_whitespace(part) for part in re.split(r"[-|:]", candidate)
            ]
            for part in parts:
                if 2 <= len(part) <= 70:
                    return part
        return extract_domain(url)

    def _likely_location(self, text: str) -> str | None:
        lowered = text.lower()
        for hint in LOCATION_HINTS:
            if hint in lowered:
                return hint.title()
        return None

    def _categories(self, *values: str) -> list[str]:
        haystack = " ".join(values).lower()
        categories = [
            category
            for category, keywords in CATEGORY_KEYWORDS.items()
            if any(keyword in haystack for keyword in keywords)
        ]
        return categories
