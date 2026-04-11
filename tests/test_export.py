from __future__ import annotations

from io import BytesIO

import pandas as pd

from growth_engine.export import ExportService
from growth_engine.models import Opportunity, OpportunityScore, SkippedEntity


def test_export_service_builds_two_sheet_workbook() -> None:
    service = ExportService()
    opportunity = Opportunity(
        priority_rank=1,
        discovery_mode="customers",
        market_side="Demand-side",
        entity_name="Example Retail",
        entity_website="https://example.com",
        entity_domain="example.com",
        category="Retail",
        location="India",
        company_size="SMB",
        budget_signal="Medium",
        expected_value="High",
        timing_signal="Active",
        decision_maker="Riya Sharma",
        decision_maker_email="riya.sharma@example.com",
        email_validation="score 2/3",
        contact_path="hello@example.com",
        source_type="public_web",
        source_url="https://example.com",
        priority_score=84,
        confidence=78,
        why_it_matters="Strong fit",
        reasoning_summary="Fit score 70 | Intent score 88",
        next_action="Email the partner lead",
        score=OpportunityScore(
            70, 70, 80, 60, 88, 70, 75, 65, 72, 84, 78, ["Strong fit"]
        ),
    )
    skipped = SkippedEntity(
        discovery_mode="partners",
        entity_name="Noise Listing",
        entity_website="https://noise.example",
        source_type="directory",
        source_url="https://noise.example",
        reason="Matched exclusion keyword",
    )

    export_name, payload = service.build_workbook([opportunity], [skipped])
    workbook = pd.ExcelFile(BytesIO(payload))

    assert export_name.endswith(".xlsx")
    assert workbook.sheet_names == ["Prioritized Opportunities", "Skipped Entities"]
