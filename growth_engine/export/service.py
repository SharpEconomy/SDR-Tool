from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import quote_plus

import pandas as pd
from openpyxl.comments import Comment
from openpyxl.styles import Font

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
        return self.build_workbook_from_rows(
            [item.as_export_row() for item in opportunities],
            [item.as_export_row() for item in skipped_entities],
        )

    def build_workbook_from_rows(
        self,
        opportunity_rows: list[dict[str, object]],
        skipped_rows: list[dict[str, object]],
    ) -> tuple[str, bytes]:
        normalized_opportunity_rows = [
            self._normalize_opportunity_row(row) for row in opportunity_rows
        ]
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        export_name = f"growth_opportunities_{timestamp}.xlsx"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame(
                normalized_opportunity_rows,
                columns=EXPORT_OPPORTUNITY_COLUMNS,
            ).to_excel(writer, sheet_name="Prioritized Opportunities", index=False)
            pd.DataFrame(
                skipped_rows,
                columns=EXPORT_SKIPPED_COLUMNS,
            ).to_excel(writer, sheet_name="Skipped Entities", index=False)
            self._format_opportunity_sheet(
                writer.book["Prioritized Opportunities"],
                normalized_opportunity_rows,
            )
        return export_name, buffer.getvalue()

    def _normalize_opportunity_row(self, row: dict[str, object]) -> dict[str, object]:
        entity_name = self._text(row.get("entity_name"))
        decision_maker = self._text(row.get("decision_maker"))
        return {
            "market_side": self._text(row.get("market_side")),
            "entity_name": entity_name,
            "category": self._text(row.get("category")),
            "company_size": self._text(row.get("company_size")),
            "location": self._text(row.get("location")),
            "decision_maker": decision_maker,
            "decision_maker_email": self._text(row.get("decision_maker_email")),
            "_entity_link": self._entity_link(row),
            "_decision_maker_link": self._linkedin_link(decision_maker, entity_name),
            "_entity_comment": self._combined_summary(row),
        }

    def _format_opportunity_sheet(
        self, worksheet, rows: list[dict[str, object]]
    ) -> None:
        header_index = {
            str(cell.value): cell.column
            for cell in worksheet[1]
            if cell.value is not None
        }
        entity_column = header_index.get("entity_name")
        decision_maker_column = header_index.get("decision_maker")
        hyperlink_font = Font(color="0563C1", underline="single")

        for row_number, row in enumerate(rows, start=2):
            if entity_column is not None:
                entity_cell = worksheet.cell(row=row_number, column=entity_column)
                entity_link = self._text(row.get("_entity_link"))
                if entity_link and entity_cell.value:
                    entity_cell.hyperlink = entity_link
                    entity_cell.font = hyperlink_font
                entity_comment = self._text(row.get("_entity_comment"))
                if entity_comment and entity_cell.value:
                    entity_cell.comment = Comment(entity_comment, "Growth Engine")

            if decision_maker_column is not None:
                decision_cell = worksheet.cell(
                    row=row_number, column=decision_maker_column
                )
                decision_link = self._text(row.get("_decision_maker_link"))
                if decision_link and decision_cell.value:
                    decision_cell.hyperlink = decision_link
                    decision_cell.font = hyperlink_font

    def _combined_summary(self, row: dict[str, object]) -> str:
        segments = [
            self._text(row.get("why_it_matters")),
            self._text(row.get("reasoning_summary")),
        ]
        return " ".join(segment for segment in segments if segment)

    def _entity_link(self, row: dict[str, object]) -> str:
        entity_website = self._normalized_url(row.get("entity_website"))
        if entity_website:
            return entity_website
        return self._normalized_url(row.get("entity_domain"))

    def _linkedin_link(self, decision_maker: str, entity_name: str) -> str:
        if not decision_maker:
            return ""
        query = quote_plus(
            " ".join(part for part in [decision_maker, entity_name] if part)
        )
        return f"https://www.linkedin.com/search/results/people/?keywords={query}"

    def _normalized_url(self, value: object) -> str:
        text = self._text(value)
        if not text:
            return ""
        if "://" in text:
            return text
        return f"https://{text}"

    def _text(self, value: object) -> str:
        return str(value or "").strip()
