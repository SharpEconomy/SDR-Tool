from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    smtp_from_email: str
    request_timeout_seconds: int
    smtp_timeout_seconds: int
    max_events_per_source: int
    max_contacts_per_company: int
    max_source_workers: int
    max_enrichment_workers: int
    default_keywords: list[str]
    default_sources: list[str]
    use_browser_fallback: bool
    website_precheck_required: bool
    smtp_precheck_required: bool
    min_validation_score: int
    qualification_enabled: bool
    use_openai_qualification: bool
    openai_api_key: str
    openai_model: str
    qualification_recent_months: int
    qualification_preferred_recent_months: int
    google_search_api_key: str
    google_search_engine_id: str

    @classmethod
    def load(cls) -> "Settings":
        qualification_recent_months = max(
            3,
            _as_int(os.getenv("QUALIFICATION_RECENT_MONTHS"), 6),
        )
        qualification_preferred_recent_months = max(
            1,
            min(
                qualification_recent_months,
                _as_int(
                    os.getenv("QUALIFICATION_PREFERRED_RECENT_MONTHS"),
                    3,
                ),
            ),
        )
        return cls(
            smtp_from_email=os.getenv("SMTP_FROM_EMAIL", "").strip(),
            request_timeout_seconds=_as_int(os.getenv("REQUEST_TIMEOUT_SECONDS"), 20),
            smtp_timeout_seconds=_as_int(os.getenv("SMTP_TIMEOUT_SECONDS"), 10),
            max_events_per_source=_as_int(os.getenv("MAX_EVENTS_PER_SOURCE"), 8),
            max_contacts_per_company=_as_int(os.getenv("MAX_CONTACTS_PER_COMPANY"), 5),
            max_source_workers=_as_int(os.getenv("MAX_SOURCE_WORKERS"), 4),
            max_enrichment_workers=_as_int(os.getenv("MAX_ENRICHMENT_WORKERS"), 8),
            default_keywords=_as_list(
                os.getenv("DEFAULT_KEYWORDS"),
                ["ai", "genai", "llm", "agent", "web3", "blockchain", "crypto"],
            ),
            default_sources=_as_list(
                os.getenv("DEFAULT_SOURCES"),
                ["ethglobal", "devpost", "dorahacks", "mlh"],
            ),
            use_browser_fallback=_as_bool(os.getenv("USE_BROWSER_FALLBACK"), True),
            website_precheck_required=_as_bool(
                os.getenv("WEBSITE_PRECHECK_REQUIRED"), True
            ),
            smtp_precheck_required=_as_bool(os.getenv("SMTP_PRECHECK_REQUIRED"), True),
            min_validation_score=_as_int(os.getenv("MIN_VALIDATION_SCORE"), 2),
            qualification_enabled=_as_bool(
                os.getenv("QUALIFICATION_ENABLED"),
                True,
            ),
            use_openai_qualification=_as_bool(
                os.getenv("USE_OPENAI_QUALIFICATION"),
                True,
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv(
                "OPENAI_MODEL",
                "gpt-5.4-mini",
            ).strip(),
            qualification_recent_months=qualification_recent_months,
            qualification_preferred_recent_months=(
                qualification_preferred_recent_months
            ),
            google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY", "").strip(),
            google_search_engine_id=os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip(),
        )
