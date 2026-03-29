from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests
from ddgs import DDGS

from hackindia_leads.config import Settings

GOOGLE_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
MONTH_NAME_PATTERNS = (
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y-%m-%d",
)
ABSOLUTE_DATE_RE = re.compile(
    r"\b(?:"
    r"[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}"
    r"|"
    r"\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4}"
    r"|"
    r"\d{4}-\d{2}-\d{2}"
    r")\b"
)
RELATIVE_DATE_RE = re.compile(r"\b(\d+)\s+(day|week|month)s?\s+ago\b", re.IGNORECASE)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: date | None = None


class SearchClient:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def search(
        self,
        query: str,
        max_results: int = 10,
        recent_months: int | None = None,
    ) -> list[SearchResult]:
        if self._can_use_google_custom_search():
            results = self._google_custom_search(query, max_results, recent_months)
        else:
            results = self._ddgs_search(query, max_results, recent_months)
        return self._apply_recency_filter(results, max_results, recent_months)

    def _can_use_google_custom_search(self) -> bool:
        return bool(
            self.settings
            and self.settings.google_search_api_key
            and self.settings.google_search_engine_id
        )

    def _google_custom_search(
        self,
        query: str,
        max_results: int,
        recent_months: int | None,
    ) -> list[SearchResult]:
        fetch_limit = max_results if recent_months is None else max_results * 3
        try:
            response = self.session.get(
                GOOGLE_CUSTOM_SEARCH_URL,
                params={
                    "key": self.settings.google_search_api_key,
                    "cx": self.settings.google_search_engine_id,
                    "q": query,
                    "num": max(1, min(fetch_limit, 10)),
                    **(
                        {"dateRestrict": f"m{recent_months}"}
                        if recent_months is not None
                        else {}
                    ),
                },
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return self._ddgs_search(query, max_results, recent_months)

        results: list[SearchResult] = []
        for item in payload.get("items", []):
            link = item.get("link")
            if not link:
                continue
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            results.append(
                SearchResult(
                    title=title,
                    url=link,
                    snippet=snippet,
                    published_at=self._extract_published_at(f"{title} {snippet}"),
                )
            )
        return results

    def _ddgs_search(
        self,
        query: str,
        max_results: int,
        recent_months: int | None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        fetch_limit = max_results if recent_months is None else max_results * 3
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=fetch_limit):
                    href = item.get("href") or item.get("url")
                    if not href:
                        continue
                    title = item.get("title", "")
                    snippet = item.get("body", "")
                    results.append(
                        SearchResult(
                            title=title,
                            url=href,
                            snippet=snippet,
                            published_at=self._extract_published_at(
                                f"{title} {snippet}"
                            ),
                        )
                    )
        except Exception:
            return []
        return results

    def _apply_recency_filter(
        self,
        results: list[SearchResult],
        max_results: int,
        recent_months: int | None,
    ) -> list[SearchResult]:
        if recent_months is None:
            return results[:max_results]

        cutoff = date.today() - timedelta(days=recent_months * 30)
        filtered = [
            result
            for result in results
            if result.published_at is not None and result.published_at >= cutoff
        ]
        filtered.sort(key=lambda result: result.published_at or date.min, reverse=True)
        return filtered[:max_results]

    def _extract_published_at(self, text: str) -> date | None:
        absolute_match = ABSOLUTE_DATE_RE.search(text)
        if absolute_match:
            candidate = absolute_match.group(0)
            for date_format in MONTH_NAME_PATTERNS:
                try:
                    return datetime.strptime(candidate, date_format).date()
                except ValueError:
                    continue

        relative_match = RELATIVE_DATE_RE.search(text)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2).lower()
            if unit == "day":
                delta = timedelta(days=amount)
            elif unit == "week":
                delta = timedelta(weeks=amount)
            else:
                delta = timedelta(days=amount * 30)
            return date.today() - delta
        return None
