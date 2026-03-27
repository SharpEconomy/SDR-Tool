from __future__ import annotations

import json
import threading
from dataclasses import dataclass

import requests

from hackindia_leads.config import Settings
from hackindia_leads.models import CompanyQualification, Event, Sponsor
from hackindia_leads.services.search import SearchClient, SearchResult

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/" "{model}:generateContent"
)
MAX_SEARCH_RESULTS_PER_QUERY = 3
MAX_CONTEXT_RESULTS = 8


@dataclass(slots=True)
class _QualificationContext:
    sponsor: Sponsor
    event: Event
    website: str | None
    domain: str | None
    search_results: list[SearchResult]


class GeminiCompanyQualifier:
    def __init__(
        self,
        settings: Settings,
        search_client: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.search_client = search_client or SearchClient()
        self._cache: dict[tuple[str, str], CompanyQualification] = {}
        self._cache_lock = threading.Lock()

    def qualify(
        self,
        sponsor: Sponsor,
        event: Event,
        website: str | None,
        domain: str | None,
    ) -> CompanyQualification | None:
        if not self.is_enabled():
            return None
        cache_key = self._cache_key(sponsor, domain)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        context = _QualificationContext(
            sponsor=sponsor,
            event=event,
            website=website,
            domain=domain,
            search_results=self._collect_search_results(sponsor),
        )
        payload = self._build_payload(context)
        response = requests.post(
            GEMINI_API_URL.format(model=self.settings.gemini_model),
            params={"key": self.settings.gemini_api_key},
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        qualification = self._parse_response(response.json())
        with self._cache_lock:
            self._cache[cache_key] = qualification
        return qualification

    def is_enabled(self) -> bool:
        return self.settings.gemini_enabled and bool(self.settings.gemini_api_key)

    def _collect_search_results(self, sponsor: Sponsor) -> list[SearchResult]:
        queries = [
            f'"{sponsor.name}" funding raised startup',
            f'"{sponsor.name}" headquarters location',
            f'"{sponsor.name}" api sdk developer platform ecosystem',
        ]
        seen: set[str] = set()
        results: list[SearchResult] = []
        for query in queries:
            for item in self.search_client.search(
                query, max_results=MAX_SEARCH_RESULTS_PER_QUERY
            ):
                key = item.url.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= MAX_CONTEXT_RESULTS:
                    return results
        return results

    def _cache_key(self, sponsor: Sponsor, domain: str | None) -> tuple[str, str]:
        company = sponsor.name.strip().lower()
        normalized_domain = (domain or "").strip().lower()
        return company, normalized_domain

    def _build_payload(self, context: _QualificationContext) -> dict[str, object]:
        prompt = self._build_prompt(context)
        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "OBJECT",
                    "properties": {
                        "company_segment": {"type": "STRING"},
                        "recently_funded": {"type": "BOOLEAN"},
                        "recent_funding_signal": {"type": "STRING"},
                        "company_location": {"type": "STRING"},
                        "location_priority": {"type": "STRING"},
                        "developer_adoption_need": {"type": "BOOLEAN"},
                        "market_visibility_need": {"type": "BOOLEAN"},
                        "qualification_notes": {"type": "STRING"},
                        "score": {"type": "INTEGER"},
                        "accepted": {"type": "BOOLEAN"},
                    },
                    "required": [
                        "company_segment",
                        "recently_funded",
                        "recent_funding_signal",
                        "company_location",
                        "location_priority",
                        "developer_adoption_need",
                        "market_visibility_need",
                        "qualification_notes",
                        "score",
                        "accepted",
                    ],
                },
            },
        }

    def _build_prompt(self, context: _QualificationContext) -> str:
        event = context.event
        sponsor = context.sponsor
        search_context = "\n".join(
            (f"- {item.title}\n" f"  URL: {item.url}\n" f"  Snippet: {item.snippet}")
            for item in context.search_results
        )
        if not search_context:
            search_context = "- No public search context was found."

        return (
            "You are qualifying outbound sponsor leads for developer-relations and "
            "market-visibility outreach.\n"
            "Return a single JSON object only.\n\n"
            "Accept a company only when all of these are true:\n"
            "1. The company is in tech, AI, or Web3.\n"
            "2. (Optional) The company appears to have raised funding recently, "
            "ideally within "
            "the last 24 months.\n"
            "3. The company would likely benefit from developer adoption, developer "
            "ecosystem growth, or stronger market visibility.\n"
            "4. Global companies are allowed, but companies based in the US or India "
            "should be prioritized.\n\n"
            "Allowed values:\n"
            '- company_segment: "Tech", "AI", "Web3", or "Other"\n'
            '- location_priority: "US", "India", "Global", or "Unknown"\n\n'
            "Be conservative. If the evidence is weak, set accepted to false.\n\n"
            f"Sponsor company: {sponsor.name}\n"
            f"Sponsor website: {context.website or sponsor.website or 'Unknown'}\n"
            f"Sponsor domain: {context.domain or 'Unknown'}\n"
            f"Source event: {event.title}\n"
            f"Event source: {event.source}\n"
            f"Event summary: {event.summary or 'Unknown'}\n"
            f"Sponsor evidence on event page: {sponsor.evidence or 'Unknown'}\n\n"
            f"Public web context:\n{search_context}\n"
        )

    def _parse_response(self, payload: dict[str, object]) -> CompanyQualification:
        response_text = self._extract_response_text(payload)
        parsed = json.loads(response_text)
        segment = self._normalize_segment(parsed.get("company_segment"))
        location_priority = (
            str(parsed.get("location_priority") or "").strip().title() or "Unknown"
        )
        if location_priority not in {"Us", "India", "Global", "Unknown"}:
            location_priority = "Unknown"
        if location_priority == "Us":
            location_priority = "US"

        return CompanyQualification(
            company_segment=segment,
            recently_funded=self._as_bool(parsed.get("recently_funded")),
            recent_funding_signal=self._clean_text(parsed.get("recent_funding_signal")),
            company_location=self._clean_text(parsed.get("company_location")),
            location_priority=location_priority,
            developer_adoption_need=self._as_bool(
                parsed.get("developer_adoption_need")
            ),
            market_visibility_need=self._as_bool(parsed.get("market_visibility_need")),
            qualification_notes=self._clean_text(parsed.get("qualification_notes")),
            score=self._as_int(parsed.get("score")),
            accepted=self._as_bool(parsed.get("accepted"), default=False),
        )

    def _normalize_segment(self, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "ai":
            return "AI"
        if normalized == "web3":
            return "Web3"
        if normalized == "tech":
            return "Tech"
        return "Other"

    def _extract_response_text(self, payload: dict[str, object]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini returned no candidates.")
        first = candidates[0]
        if not isinstance(first, dict):
            raise ValueError("Gemini returned an invalid candidate payload.")
        content = first.get("content")
        if not isinstance(content, dict):
            raise ValueError("Gemini returned no content.")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Gemini returned no parts.")
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
        raise ValueError("Gemini returned no text content.")

    def _as_bool(self, value: object, default: bool | None = None) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes"}:
                return True
            if lowered in {"false", "no"}:
                return False
        return default

    def _as_int(self, value: object) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return 0

    def _clean_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
