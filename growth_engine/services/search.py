from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

import requests
from ddgs import DDGS

from growth_engine.config import Settings
from growth_engine.models import SearchResult

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


class SearchClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self._can_use_google_custom_search():
            results = self._google_custom_search(query, max_results)
            if results:
                return results[:max_results]
        return self._ddgs_search(query, max_results)

    def _can_use_google_custom_search(self) -> bool:
        return bool(
            self.settings.google_search_api_key
            and self.settings.google_search_engine_id
        )

    def _google_custom_search(
        self,
        query: str,
        max_results: int,
    ) -> list[SearchResult]:
        payload = None
        for attempt in range(1, self.settings.request_retry_attempts + 2):
            try:
                response = self.session.get(
                    GOOGLE_CUSTOM_SEARCH_URL,
                    params={
                        "key": self.settings.google_search_api_key,
                        "cx": self.settings.google_search_engine_id,
                        "q": query,
                        "num": max(1, min(max_results, 10)),
                    },
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                break
            except Exception:
                if attempt > self.settings.request_retry_attempts:
                    return []
                time.sleep(self.settings.request_retry_backoff_seconds * attempt)

        results: list[SearchResult] = []
        for item in payload.get("items", []):
            link = item.get("link")
            if not link:
                continue
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            results.append(
                SearchResult(
                    title=title,
                    url=link,
                    snippet=snippet,
                    published_at=self._extract_published_at(f"{title} {snippet}"),
                )
            )
        return results

    def _ddgs_search(self, query: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for attempt in range(1, self.settings.request_retry_attempts + 2):
            try:
                with DDGS() as ddgs:
                    for item in ddgs.text(query, max_results=max_results):
                        href = item.get("href") or item.get("url")
                        if not href:
                            continue
                        title = str(item.get("title", "")).strip()
                        snippet = str(item.get("body", "")).strip()
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
                break
            except Exception:
                if attempt > self.settings.request_retry_attempts:
                    return []
                time.sleep(self.settings.request_retry_backoff_seconds * attempt)
        return results

    def _extract_published_at(self, text: str) -> datetime | None:
        match = ABSOLUTE_DATE_RE.search(text)
        if not match:
            return None
        candidate = match.group(0)
        for date_format in MONTH_NAME_PATTERNS:
            try:
                return datetime.strptime(candidate, date_format)
            except ValueError:
                continue
        if candidate.count("-") == 2:
            try:
                return datetime.strptime(candidate, "%Y-%m-%d")
            except ValueError:
                return None
        return None


def freshness_label(published_at: datetime | None) -> str:
    if published_at is None:
        return "unknown"
    age = datetime.utcnow() - published_at
    if age <= timedelta(days=30):
        return "fresh"
    if age <= timedelta(days=120):
        return "recent"
    return "stale"
