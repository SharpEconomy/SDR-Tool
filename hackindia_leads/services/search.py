from __future__ import annotations

from dataclasses import dataclass

import requests
from ddgs import DDGS

from hackindia_leads.config import Settings

GOOGLE_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchClient:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if self._can_use_google_custom_search():
            return self._google_custom_search(query, max_results)
        return self._ddgs_search(query, max_results)

    def _can_use_google_custom_search(self) -> bool:
        return bool(
            self.settings
            and self.settings.google_search_api_key
            and self.settings.google_search_engine_id
        )

    def _google_custom_search(self, query: str, max_results: int) -> list[SearchResult]:
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
        except Exception:
            return self._ddgs_search(query, max_results)

        results: list[SearchResult] = []
        for item in payload.get("items", []):
            link = item.get("link")
            if not link:
                continue
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=link,
                    snippet=item.get("snippet", ""),
                )
            )
        return results

    def _ddgs_search(self, query: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    href = item.get("href") or item.get("url")
                    if not href:
                        continue
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=href,
                            snippet=item.get("body", ""),
                        )
                    )
        except Exception:
            return []
        return results
