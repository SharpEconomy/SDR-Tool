from __future__ import annotations

import os
from datetime import UTC, datetime

import django
import pytest

from growth_engine.config import Settings
from growth_engine.models import BusinessIntake, SearchResult

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "growth_engine_django.settings")
django.setup()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_name="Growth Opportunity Decision Engine",
        app_base_url="",
        request_timeout_seconds=5,
        request_retry_attempts=1,
        request_retry_backoff_seconds=0,
        smtp_timeout_seconds=5,
        max_fetch_workers=2,
        max_validation_workers=2,
        max_results_per_adapter=3,
        max_opportunities=10,
        max_llm_refinements=3,
        use_browser_fallback=False,
        smtp_probe_enabled=False,
        min_email_validation_score=2,
        openai_enabled=True,
        openai_api_key="test-key",
        openai_model="gpt-5.4-mini",
        openai_reasoning_effort="low",
        google_search_api_key="",
        google_search_engine_id="",
        audit_backend="local",
        firestore_collection="growth_runs",
        firestore_profile_collection="growth_profiles",
        firestore_database="(default)",
        google_cloud_project="demo-project",
        google_cloud_service_account_json_b64="",
        firebase_storage_bucket="",
        google_oauth_client_id="",
        google_oauth_client_secret="",
        google_oauth_redirect_uri="",
        admin_emails=["admin@example.com"],
        default_discovery_modes=["customers", "partners"],
        default_target_geographies=["India"],
    )


@pytest.fixture
def intake() -> BusinessIntake:
    return BusinessIntake(
        business_name="Aarohan Foods",
        website="aarohanfoods.example",
        description="Healthy snack manufacturer growing through retail and distributor channels.",
        industry="Food and beverage",
        location="Mumbai, India",
        target_geographies=["India", "Maharashtra"],
        budget="Balanced",
        ideal_customer_profile="Retail chains and distribution partners",
        preferred_company_sizes=["SMB", "Mid Market"],
        preferred_sectors=["Retail", "Distribution"],
        offerings=["Healthy snacks", "Private label packs"],
        goals=["Expand into modern trade", "Find reliable supply partners"],
        discovery_modes=["customers", "partners"],
        opportunity_type_needed="Distributors and channel partners",
        inclusion_keywords=["distribution", "retail", "procurement"],
        exclusion_keywords=["job board", "event"],
        vendor_constraints="India-first logistics",
        supplier_constraints="Avoid unverified factories",
        user_urls=["https://example.com/opportunity"],
    )


@pytest.fixture
def linkedin_search_result() -> list[SearchResult]:
    return [
        SearchResult(
            title="Riya Sharma - Head of Partnerships - Example Retail | LinkedIn",
            url="https://www.linkedin.com/in/riya-sharma/",
            snippet="Riya Sharma - Head of Partnerships - Example Retail",
            published_at=datetime.now(UTC),
        )
    ]


@pytest.fixture(autouse=True)
def patch_runtime_settings(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "growth_engine_web.runtime.get_runtime_settings", lambda: settings
    )
    monkeypatch.setattr(
        "growth_engine_web.views.get_runtime_settings", lambda: settings
    )
    monkeypatch.setattr(
        "growth_engine_web.context_processors.get_runtime_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "growth_engine_web.google_auth.get_runtime_settings",
        lambda: settings,
    )
