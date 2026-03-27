from __future__ import annotations

from pathlib import Path

import pytest

from hackindia_leads.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
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
        results_dir=tmp_path,
        use_browser_fallback=True,
        website_precheck_required=True,
        smtp_precheck_required=True,
        min_validation_score=2,
    )
