from __future__ import annotations

import pytest

from hackindia_leads.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        smtp_from_email="sender@example.com",
        request_timeout_seconds=5,
        smtp_timeout_seconds=5,
        max_events_per_source=3,
        max_contacts_per_company=5,
        max_source_workers=2,
        max_enrichment_workers=4,
        default_keywords=["ai", "web3"],
        default_sources=["ethglobal", "devpost"],
        use_browser_fallback=True,
        website_precheck_required=True,
        smtp_precheck_required=True,
        min_validation_score=2,
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        gemini_enabled=True,
    )
