from __future__ import annotations

from growth_engine.models import SearchResult
from growth_engine.profile_research.service import BusinessProfileResearcher


class _FakeFetcher:
    def fetch(self, url: str, prefer_browser: bool = False):
        return type(
            "Result",
            (),
            {
                "text": (
                    "<html><head><title>Demo Foods</title><meta name='description' "
                    "content='Healthy snack manufacturer in Mumbai for retail and distribution.' /></head>"
                    "<body><h1>Healthy snacks for retail partners</h1></body></html>"
                ),
            },
        )()


class _FakeSearchClient:
    def search(self, query: str, max_results: int = 3):
        return [
            SearchResult(
                title="Demo Foods company profile",
                url="https://directory.example/demo-foods",
                snippet="Demo Foods is a Mumbai food manufacturer serving retail distributors.",
            )
        ]


class _MixedSearchClient:
    def search(self, query: str, max_results: int = 3):
        return [
            SearchResult(
                title="Download the YouTube mobile app - Android - YouTube Help",
                url="https://support.google.com/youtube/answer/3227660?hl=en",
                snippet="Download the YouTube app for a richer viewing experience on your smartphone.",
            ),
            SearchResult(
                title="Demo Foods company profile",
                url="https://directory.example/demo-foods",
                snippet="Demo Foods is a Mumbai food manufacturer serving retail distributors.",
            ),
        ]


class _FakeOpenAIService:
    def is_available(self) -> bool:
        return True

    def verify_business_profile(self, payload):
        return {
            "description": "Healthy snack manufacturer for retail and distributor channels.",
            "industry": "Food and beverage",
            "location": "Mumbai, India",
            "target_geographies": ["India", "UAE"],
            "budget": "Balanced",
            "ideal_customer_profile": "Retail chains and distributors",
            "preferred_company_sizes": ["SMB", "Mid-market"],
            "preferred_sectors": ["Retail", "Distribution"],
            "offerings": ["Healthy snacks", "Private label packs"],
            "goals": ["Grow retail reach"],
            "discovery_modes": ["customers", "partners"],
            "opportunity_type_needed": "Retail buyers and channel partners",
            "inclusion_keywords": ["retail", "distribution"],
            "exclusion_keywords": ["jobs"],
            "vendor_constraints": "None",
            "supplier_constraints": "None",
            "user_urls": ["https://demo.example"],
            "verification_summary": "The website and search evidence align on a Mumbai food brand focused on retail distribution.",
        }


def test_profile_researcher_builds_verified_draft(settings) -> None:
    researcher = BusinessProfileResearcher(
        settings,
        fetcher=_FakeFetcher(),
        search_client=_FakeSearchClient(),
        openai_service=_FakeOpenAIService(),
    )

    result = researcher.research(
        business_name="Demo Foods",
        website="demo.example",
    )

    assert result.draft.business_name == "Demo Foods"
    assert result.draft.website == "https://demo.example"
    assert result.draft.industry == "Food and beverage"
    assert result.draft.discovery_modes == ["customers", "partners"]
    assert result.sources
    assert "website and search evidence align" in result.verification_summary.lower()


class _UnavailableOpenAIService:
    def is_available(self) -> bool:
        return False


def test_profile_researcher_falls_back_without_model(settings) -> None:
    researcher = BusinessProfileResearcher(
        settings,
        fetcher=_FakeFetcher(),
        search_client=_FakeSearchClient(),
        openai_service=_UnavailableOpenAIService(),
    )

    result = researcher.research(
        business_name="Demo Foods",
        website="demo.example",
    )

    assert result.draft.description
    assert result.draft.discovery_modes == settings.default_discovery_modes
    assert result.draft.user_urls[0] == "https://demo.example"


def test_profile_researcher_filters_irrelevant_search_results(settings) -> None:
    researcher = BusinessProfileResearcher(
        settings,
        fetcher=_FakeFetcher(),
        search_client=_MixedSearchClient(),
        openai_service=_UnavailableOpenAIService(),
    )

    result = researcher.research(
        business_name="Demo Foods",
        website="demo.example",
    )

    source_urls = [source.url for source in result.sources]

    assert "https://directory.example/demo-foods" in source_urls
    assert not any("support.google.com/youtube" in url for url in source_urls)
