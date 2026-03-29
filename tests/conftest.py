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
        qualification_enabled=True,
        use_claude_qualification=True,
        anthropic_api_key="test-anthropic-key",
        anthropic_model="claude-sonnet-4-20250514",
        qualification_recent_months=6,
        qualification_preferred_recent_months=3,
        google_search_api_key="",
        google_search_engine_id="",
    )
