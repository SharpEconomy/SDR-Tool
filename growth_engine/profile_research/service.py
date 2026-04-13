from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict

from growth_engine.config import Settings
from growth_engine.models import (
    IntakeDraft,
    ProfileResearchResult,
    ResearchSource,
    SearchResult,
)
from growth_engine.parsing.html import HtmlParsingService
from growth_engine.services.fetcher import PageFetcher
from growth_engine.services.openai_service import ModelUnavailableError, OpenAIService
from growth_engine.services.search import SearchClient
from growth_engine.utils import (
    dedupe_keep_order,
    extract_domain,
    normalize_url,
    normalize_whitespace,
)


class BusinessProfileResearcher:
    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: PageFetcher | None = None,
        search_client: SearchClient | None = None,
        openai_service: OpenAIService | None = None,
        parser: HtmlParsingService | None = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher or PageFetcher(settings)
        self.search_client = search_client or SearchClient(settings)
        self.openai_service = openai_service or OpenAIService(settings)
        self.parser = parser or HtmlParsingService()
        self._custom_fetcher = fetcher is not None
        self._custom_search_client = search_client is not None
        self._custom_openai_service = openai_service is not None

    def research(
        self,
        *,
        business_name: str,
        website: str,
    ) -> ProfileResearchResult:
        normalized_name = normalize_whitespace(business_name)
        normalized_website = normalize_url(website) or normalize_whitespace(website)
        domain = extract_domain(normalized_website) or ""

        website_source, search_sources = self._collect_sources_parallel(
            normalized_website, normalized_name, domain
        )
        sources = dedupe_sources(
            [
                source
                for source in [website_source, *search_sources]
                if source is not None
            ]
        )

        model_payload = {
            "business_name": normalized_name,
            "website": normalized_website,
            "sources": [asdict(source) for source in sources],
            "default_discovery_modes": self.settings.default_discovery_modes,
            "default_target_geographies": self.settings.default_target_geographies,
        }
        model_result = self._model_profile_parallel(model_payload)
        draft = self._build_draft(
            business_name=normalized_name,
            website=normalized_website,
            sources=sources,
            model_result=model_result,
        )
        return ProfileResearchResult(
            draft=draft,
            sources=sources,
            verification_summary=str(
                model_result.get("verification_summary")
                or self._fallback_summary(sources)
            ).strip(),
        )

    def _website_source(self, website: str) -> ResearchSource | None:
        if not website:
            return None
        result = self.fetcher.fetch(website, prefer_browser=True)
        if not result.text:
            return ResearchSource(
                kind="website",
                url=website,
                title="Primary website",
                snippet=(
                    "The homepage could not be fetched. Review this field manually "
                    "before saving."
                ),
            )
        parsed = self.parser.parse(
            type(
                "Document",
                (),
                {
                    "html": result.text,
                    "title": "",
                    "url": website,
                },
            )()
        )
        snippet = " ".join(
            item
            for item in [
                parsed.title,
                parsed.meta_description,
                " ".join(parsed.headings[:3]),
                parsed.visible_text[:600],
            ]
            if normalize_whitespace(item)
        )
        return ResearchSource(
            kind="website",
            url=website,
            title=parsed.title or "Primary website",
            snippet=normalize_whitespace(snippet)[:900],
        )

    def _collect_sources_parallel(
        self,
        website: str,
        business_name: str,
        domain: str,
    ) -> tuple[ResearchSource | None, list[ResearchSource]]:
        if self._custom_fetcher or self._custom_search_client:
            return (
                self._website_source(website),
                self._search_sources(business_name, domain),
            )
        queries = [
            f'"{business_name}" "{domain}"' if domain else business_name,
            f"site:{domain} about" if domain else f'"{business_name}" company',
            f'"{business_name}" industry location',
        ]
        tasks: list[tuple[str, str]] = []
        if website:
            tasks.append(("website", website))
        for query in queries:
            tasks.append(("search", query))

        if not tasks:
            return None, []

        website_source: ResearchSource | None = None
        search_results: list[SearchResult] = []

        with _parallel_executor(len(tasks)) as executor:
            futures = []
            for task_type, payload in tasks:
                if task_type == "website":
                    futures.append(
                        executor.submit(_website_source_worker, self.settings, payload)
                    )
                else:
                    futures.append(
                        executor.submit(_search_query_worker, self.settings, payload, 3)
                    )
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    continue
                if isinstance(result, dict) and result.get("kind") == "website":
                    website_source = ResearchSource(**result)
                elif isinstance(result, list):
                    search_results.extend(result)

        filtered_sources = self._filter_search_sources(
            search_results, business_name, domain
        )
        return website_source, filtered_sources

    def _filter_search_sources(
        self,
        results: list[SearchResult],
        business_name: str,
        domain: str,
    ) -> list[ResearchSource]:
        sources: list[ResearchSource] = []
        seen_urls: set[str] = set()
        for result in results:
            normalized_url = normalize_whitespace(result.url)
            if not normalized_url or normalized_url in seen_urls:
                continue
            if not self._is_relevant_search_result(
                business_name=business_name,
                domain=domain,
                title=str(result.title or ""),
                snippet=str(result.snippet or ""),
                url=normalized_url,
            ):
                continue
            seen_urls.add(normalized_url)
            sources.append(
                ResearchSource(
                    kind="search",
                    url=normalized_url,
                    title=normalize_whitespace(result.title) or normalized_url,
                    snippet=normalize_whitespace(result.snippet),
                )
            )
            if len(sources) >= 6:
                return sources
        return sources

    def _search_sources(self, business_name: str, domain: str) -> list[ResearchSource]:
        queries = [
            f'"{business_name}" "{domain}"' if domain else business_name,
            f"site:{domain} about" if domain else f'"{business_name}" company',
            f'"{business_name}" industry location',
        ]
        sources: list[ResearchSource] = []
        seen_urls: set[str] = set()
        for query in queries:
            for result in self.search_client.search(query, max_results=3):
                normalized_url = normalize_whitespace(result.url)
                if not normalized_url or normalized_url in seen_urls:
                    continue
                if not self._is_relevant_search_result(
                    business_name=business_name,
                    domain=domain,
                    title=str(result.title or ""),
                    snippet=str(result.snippet or ""),
                    url=normalized_url,
                ):
                    continue
                seen_urls.add(normalized_url)
                sources.append(
                    ResearchSource(
                        kind="search",
                        url=normalized_url,
                        title=normalize_whitespace(result.title) or normalized_url,
                        snippet=normalize_whitespace(result.snippet),
                    )
                )
                if len(sources) >= 6:
                    return sources
        return sources

    def _is_relevant_search_result(
        self,
        *,
        business_name: str,
        domain: str,
        title: str,
        snippet: str,
        url: str,
    ) -> bool:
        haystack = normalize_whitespace(f"{title} {snippet} {url}").lower()
        url_domain = extract_domain(url) or ""
        name_tokens = [
            token
            for token in normalize_whitespace(business_name)
            .lower()
            .replace("-", " ")
            .split()
            if len(token) >= 4
        ]
        matched_name_tokens = [token for token in name_tokens if token in haystack]
        blocked_terms = {
            "youtube help",
            "support.google.com",
            "play.google.com",
            "apps.apple.com",
            "download the app",
            "mobile app",
            "help center",
            "privacy policy",
            "terms of service",
            "sign in",
            "login",
        }
        if any(term in haystack for term in blocked_terms):
            return False
        if domain and (domain in url_domain or domain in haystack):
            return True
        return (
            len(matched_name_tokens) >= min(2, len(name_tokens))
            if name_tokens
            else False
        )

    def _model_profile(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            if self.openai_service.is_available():
                return self.openai_service.verify_business_profile(payload)
        except ModelUnavailableError:
            pass
        return {}

    def _model_profile_parallel(self, payload: dict[str, object]) -> dict[str, object]:
        if not self.openai_service.is_available():
            return {}
        if self._custom_openai_service:
            return self._model_profile(payload)
        try:
            with _parallel_executor(1) as executor:
                future = executor.submit(
                    _verify_profile_worker,
                    self.settings,
                    payload,
                )
                return future.result()
        except Exception:
            return self._model_profile(payload)

    def _build_draft(
        self,
        *,
        business_name: str,
        website: str,
        sources: list[ResearchSource],
        model_result: dict[str, object],
    ) -> IntakeDraft:
        description = clean_text(
            model_result.get("description")
        ) or first_source_snippet(sources)
        industry = clean_text(model_result.get("industry")) or infer_industry(sources)
        location = clean_text(model_result.get("location")) or safe_first_list(
            self.settings.default_target_geographies
        )
        offerings = clean_list(model_result.get("offerings")) or fallback_keywords(
            description, limit=3
        )
        goals = clean_list(model_result.get("goals")) or ["Grow qualified demand"]
        discovery_modes = clean_list(model_result.get("discovery_modes")) or list(
            self.settings.default_discovery_modes
        )
        preferred_sectors = clean_list(model_result.get("preferred_sectors")) or (
            [industry] if industry else []
        )
        target_geographies = clean_list(model_result.get("target_geographies")) or (
            [location] if location else list(self.settings.default_target_geographies)
        )
        inclusion_keywords = clean_list(
            model_result.get("inclusion_keywords")
        ) or dedupe_keep_order(offerings + preferred_sectors)
        user_urls = dedupe_keep_order(
            [website] + [source.url for source in sources if source.url]
        )
        ideal_customer_profile = clean_text(
            model_result.get("ideal_customer_profile")
        ) or build_default_icp(description, industry)
        opportunity_type_needed = clean_text(
            model_result.get("opportunity_type_needed")
        ) or build_default_need(discovery_modes)

        return IntakeDraft(
            business_name=business_name,
            website=website,
            description=description,
            industry=industry,
            location=location,
            target_geographies=target_geographies,
            budget=clean_text(model_result.get("budget")) or "Not specified",
            ideal_customer_profile=ideal_customer_profile,
            preferred_company_sizes=clean_list(
                model_result.get("preferred_company_sizes")
            )
            or ["SMB", "Mid-market"],
            preferred_sectors=preferred_sectors,
            offerings=offerings,
            goals=goals,
            discovery_modes=discovery_modes,
            opportunity_type_needed=opportunity_type_needed,
            inclusion_keywords=inclusion_keywords,
            exclusion_keywords=clean_list(model_result.get("exclusion_keywords")),
            vendor_constraints=clean_text(model_result.get("vendor_constraints"))
            or "None",
            supplier_constraints=clean_text(model_result.get("supplier_constraints"))
            or "None",
            user_urls=user_urls,
        )

    def _fallback_summary(self, sources: list[ResearchSource]) -> str:
        if not sources:
            return (
                "No public evidence was fetched. Review every field manually before "
                "saving."
            )
        return (
            "Built the draft from the primary website and supporting search results. "
            "Review and adjust any field that needs a business-side correction "
            "before saving."
        )


def dedupe_sources(sources: list[ResearchSource]) -> list[ResearchSource]:
    seen: set[str] = set()
    output: list[ResearchSource] = []
    for source in sources:
        key = normalize_whitespace(source.url).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(source)
    return output


def clean_text(value: object) -> str:
    return normalize_whitespace(str(value or ""))


def clean_list(value: object) -> list[str]:
    if isinstance(value, list):
        return dedupe_keep_order([str(item) for item in value])
    if isinstance(value, str):
        return dedupe_keep_order(
            [item.strip() for item in value.split(",") if item.strip()]
        )
    return []


def first_source_snippet(sources: list[ResearchSource]) -> str:
    for source in sources:
        if source.kind == "website" and source.snippet:
            return source.snippet[:240]
    for source in sources:
        if source.snippet:
            return source.snippet[:240]
    return ""


def infer_industry(sources: list[ResearchSource]) -> str:
    haystack = " ".join(source.snippet for source in sources).lower()
    candidates = (
        ("software", "Software"),
        ("saas", "Software"),
        ("manufacturer", "Manufacturing"),
        ("manufacturing", "Manufacturing"),
        ("logistics", "Logistics"),
        ("retail", "Retail"),
        ("healthcare", "Healthcare"),
        ("food", "Food and beverage"),
        ("beverage", "Food and beverage"),
        ("consulting", "Professional services"),
        ("agency", "Professional services"),
    )
    for keyword, label in candidates:
        if keyword in haystack:
            return label
    return "Not specified"


def fallback_keywords(value: str, *, limit: int) -> list[str]:
    tokens = dedupe_keep_order(
        [
            token
            for token in normalize_whitespace(value).replace("/", " ").split(" ")
            if len(token) > 3
        ]
    )
    return tokens[:limit]


def build_default_icp(description: str, industry: str) -> str:
    if description:
        return f"Best-fit buyers for {description[:120]}"
    if industry and industry != "Not specified":
        return f"Qualified buyers in {industry.lower()}"
    return "Qualified buyers that match the public business profile"


def build_default_need(discovery_modes: list[str]) -> str:
    if "partners" in discovery_modes and "customers" in discovery_modes:
        return "Qualified customers and channel partners"
    if discovery_modes:
        return f"Qualified {discovery_modes[0].replace('_', ' ')}"
    return "Qualified growth opportunities"


def safe_first_list(items: list[str]) -> str:
    return normalize_whitespace(items[0]) if items else ""


def _process_workers(task_count: int) -> int:
    cpu_count = os.cpu_count() or 2
    return max(1, min(cpu_count, task_count))


def _parallel_executor(task_count: int):
    max_workers = _process_workers(task_count)
    try:
        return ProcessPoolExecutor(max_workers=max_workers)
    except Exception:
        return ThreadPoolExecutor(max_workers=max_workers)


def _website_source_worker(settings: Settings, website: str) -> dict[str, str] | None:
    if not website:
        return None
    fetcher = PageFetcher(settings)
    parser = HtmlParsingService()
    result = fetcher.fetch(website, prefer_browser=True)
    if not result.text:
        return {
            "kind": "website",
            "url": website,
            "title": "Primary website",
            "snippet": (
                "The homepage could not be fetched. Review this field manually "
                "before saving."
            ),
        }
    parsed = parser.parse(
        type(
            "Document",
            (),
            {
                "html": result.text,
                "title": "",
                "url": website,
            },
        )()
    )
    snippet = " ".join(
        item
        for item in [
            parsed.title,
            parsed.meta_description,
            " ".join(parsed.headings[:3]),
            parsed.visible_text[:600],
        ]
        if normalize_whitespace(item)
    )
    return {
        "kind": "website",
        "url": website,
        "title": parsed.title or "Primary website",
        "snippet": normalize_whitespace(snippet)[:900],
    }


def _search_query_worker(
    settings: Settings,
    query: str,
    max_results: int,
) -> list[SearchResult]:
    search_client = SearchClient(settings)
    return search_client.search(query, max_results=max_results)


def _verify_profile_worker(
    settings: Settings,
    payload: dict[str, object],
) -> dict[str, object]:
    openai_service = OpenAIService(settings)
    if not openai_service.is_available():
        return {}
    return openai_service.verify_business_profile(payload)
