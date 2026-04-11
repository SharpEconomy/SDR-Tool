from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pandas as pd

from growth_engine.models import (
    EXPORT_OPPORTUNITY_COLUMNS,
    EXPORT_SKIPPED_COLUMNS,
    Opportunity,
    SkippedEntity,
)


class ExportService:
    def build_workbook(
        self,
        opportunities: list[Opportunity],
        skipped_entities: list[SkippedEntity],
    ) -> tuple[str, bytes]:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        export_name = f"growth_opportunities_{timestamp}.xlsx"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame(
                [item.as_export_row() for item in opportunities],
                columns=EXPORT_OPPORTUNITY_COLUMNS,
            ).to_excel(writer, sheet_name="Prioritized Opportunities", index=False)
            pd.DataFrame(
                [item.as_export_row() for item in skipped_entities],
                columns=EXPORT_SKIPPED_COLUMNS,
            ).to_excel(writer, sheet_name="Skipped Entities", index=False)
        return export_name, buffer.getvalue()
