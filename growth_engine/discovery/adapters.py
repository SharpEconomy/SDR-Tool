from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from growth_engine.config import Settings
from growth_engine.discovery.base import DiscoveryAdapter
from growth_engine.models import BusinessProfile, DiscoveryDocument
from growth_engine.services.fetcher import PageFetcher
from growth_engine.services.search import SearchClient
from growth_engine.utils import dedupe_keep_order, normalize_url

MODE_TERMS = {
    "customers": ["buyers", "distributors", "retailers", "B2B customers"],
    "vendors": ["vendors", "procurement", "approved suppliers", "tender"],
    "suppliers": ["suppliers", "manufacturers", "wholesalers", "bulk sourcing"],
    "partners": ["partners", "alliances", "channel partner", "reseller"],
    "service_providers": ["agency", "consulting", "implementation partner"],
}


class UserUrlDiscoveryAdapter(DiscoveryAdapter):
    name = "user_urls"
    source_type = "user_url"

    def __init__(self, settings: Settings, fetcher: PageFetcher) -> None:
        self.settings = settings
        self.fetcher = fetcher

    def discover(
        self,
        profile: BusinessProfile,
        discovery_mode: str,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[DiscoveryDocument]:
        urls = [normalize_url(url) for url in profile.user_urls]
        urls = [url for url in urls if url]
        if not urls:
            return []
        documents: list[DiscoveryDocument] = []
        for url in urls[: self.settings.max_results_per_adapter]:
            if progress_callback is not None:
                progress_callback(f"user_urls: fetching {url}")
            result = self.fetcher.fetch(url)
            documents.append(
                DiscoveryDocument(
                    adapter_name=self.name,
                    source_type=self.source_type,
                    discovery_mode=discovery_mode,
                    url=url,
                    title=url,
                    snippet="User supplied seed URL",
                    html=result.text,
                    status_code=result.status_code,
                    fetched_at=datetime.now(UTC),
                )
            )
        return documents


class SearchDiscoveryAdapter(DiscoveryAdapter):
    def __init__(
        self,
        name: str,
        source_type: str,
        settings: Settings,
        fetcher: PageFetcher,
        search_client: SearchClient,
        query_builder: Callable[[BusinessProfile, str], list[str]],
    ) -> None:
        self.name = name
        self.source_type = source_type
        self.settings = settings
        self.fetcher = fetcher
        self.search_client = search_client
        self.query_builder = query_builder

    def discover(
        self,
        profile: BusinessProfile,
        discovery_mode: str,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[DiscoveryDocument]:
        queries = self.query_builder(profile, discovery_mode)
        urls_seen: set[str] = set()
        search_results = []
        for query in queries[: self.settings.max_results_per_adapter]:
            if progress_callback is not None:
                progress_callback(f"{self.name}: searching {query}")
            search_results.extend(
                self.search_client.search(query, self.settings.max_results_per_adapter)
            )
        deduped_results = []
        for result in search_results:
            if result.url in urls_seen:
                continue
            urls_seen.add(result.url)
            deduped_results.append(result)

        documents: list[DiscoveryDocument] = []
        with ThreadPoolExecutor(
            max_workers=min(self.settings.max_fetch_workers, len(deduped_results) or 1)
        ) as executor:
            future_map = {
                executor.submit(self.fetcher.fetch, result.url): result
                for result in deduped_results[: self.settings.max_results_per_adapter]
            }
            for future, result in future_map.items():
                fetched = future.result()
                documents.append(
                    DiscoveryDocument(
                        adapter_name=self.name,
                        source_type=self.source_type,
                        discovery_mode=discovery_mode,
                        url=result.url,
                        title=result.title,
                        snippet=result.snippet,
                        html=fetched.text,
                        status_code=fetched.status_code,
                        fetched_at=datetime.now(UTC),
                    )
                )
        return documents


def build_discovery_adapters(
    settings: Settings,
    fetcher: PageFetcher,
    search_client: SearchClient,
) -> list[DiscoveryAdapter]:
    return [
        UserUrlDiscoveryAdapter(settings, fetcher),
        SearchDiscoveryAdapter(
            name="public_web",
            source_type="public_web",
            settings=settings,
            fetcher=fetcher,
            search_client=search_client,
            query_builder=_public_web_queries,
        ),
        SearchDiscoveryAdapter(
            name="directories",
            source_type="directory",
            settings=settings,
            fetcher=fetcher,
            search_client=search_client,
            query_builder=_directory_queries,
        ),
        SearchDiscoveryAdapter(
            name="company_sites",
            source_type="company_site",
            settings=settings,
            fetcher=fetcher,
            search_client=search_client,
            query_builder=_company_site_queries,
        ),
        SearchDiscoveryAdapter(
            name="procurement",
            source_type="procurement_listing",
            settings=settings,
            fetcher=fetcher,
            search_client=search_client,
            query_builder=_procurement_queries,
        ),
    ]


def _public_web_queries(profile: BusinessProfile, discovery_mode: str) -> list[str]:
    target = " ".join(profile.targeting_model.keywords[:3])
    geography = profile.target_geographies[0] if profile.target_geographies else "India"
    return dedupe_keep_order(
        [
            f"{target} {MODE_TERMS.get(discovery_mode, [discovery_mode])[0]} {geography}",
            f"{profile.industry} {discovery_mode} {geography}",
        ]
    )


def _directory_queries(profile: BusinessProfile, discovery_mode: str) -> list[str]:
    geography = profile.target_geographies[0] if profile.target_geographies else "India"
    term = MODE_TERMS.get(discovery_mode, [discovery_mode])[0]
    return dedupe_keep_order(
        [
            f"{profile.industry} {term} directory {geography}",
            f"{term} list {profile.preferred_sectors[0] if profile.preferred_sectors else profile.industry} {geography}",
        ]
    )


def _company_site_queries(profile: BusinessProfile, discovery_mode: str) -> list[str]:
    keywords = " ".join(profile.offerings[:2] or profile.targeting_model.keywords[:2])
    term = MODE_TERMS.get(discovery_mode, [discovery_mode])[0]
    return dedupe_keep_order(
        [
            f"{keywords} {term} site:.in",
            f"{keywords} {term} official website India",
        ]
    )


def _procurement_queries(profile: BusinessProfile, discovery_mode: str) -> list[str]:
    keywords = " ".join(profile.offerings[:2] or profile.targeting_model.keywords[:2])
    geography = profile.target_geographies[0] if profile.target_geographies else "India"
    return dedupe_keep_order(
        [
            f"{keywords} tender {geography}",
            f"{keywords} rfq {geography}",
            f"{keywords} procurement {geography}",
        ]
    )
