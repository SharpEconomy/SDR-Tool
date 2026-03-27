from __future__ import annotations

from dataclasses import dataclass

from ddgs import DDGS


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchClient:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
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
