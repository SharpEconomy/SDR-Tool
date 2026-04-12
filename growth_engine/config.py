from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))
load_dotenv(dotenv_path=Path(".env.example"))


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
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    app_name: str
    request_timeout_seconds: int
    request_retry_attempts: int
    request_retry_backoff_seconds: int
    smtp_timeout_seconds: int
    max_fetch_workers: int
    max_validation_workers: int
    max_results_per_adapter: int
    max_opportunities: int
    max_llm_refinements: int
    use_browser_fallback: bool
    smtp_probe_enabled: bool
    min_email_validation_score: int
    openai_enabled: bool
    openai_api_key: str
    openai_model: str
    openai_reasoning_effort: str
    google_search_api_key: str
    google_search_engine_id: str
    audit_backend: str
    firestore_collection: str
    firestore_profile_collection: str
    firestore_database: str
    google_cloud_project: str
    google_cloud_service_account_json_b64: str
    firebase_storage_bucket: str
    firebase_api_key: str
    firebase_auth_domain: str
    firebase_project_id: str
    default_discovery_modes: list[str]
    default_target_geographies: list[str]

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            app_name=os.getenv(
                "APP_NAME",
                "Growth Opportunity Decision Engine",
            ).strip(),
            request_timeout_seconds=_as_int(os.getenv("REQUEST_TIMEOUT_SECONDS"), 20),
            request_retry_attempts=_as_int(os.getenv("REQUEST_RETRY_ATTEMPTS"), 2),
            request_retry_backoff_seconds=_as_int(
                os.getenv("REQUEST_RETRY_BACKOFF_SECONDS"),
                1,
            ),
            smtp_timeout_seconds=_as_int(os.getenv("SMTP_TIMEOUT_SECONDS"), 10),
            max_fetch_workers=_as_int(os.getenv("MAX_FETCH_WORKERS"), 6),
            max_validation_workers=_as_int(os.getenv("MAX_VALIDATION_WORKERS"), 4),
            max_results_per_adapter=_as_int(os.getenv("MAX_RESULTS_PER_ADAPTER"), 5),
            max_opportunities=_as_int(os.getenv("MAX_OPPORTUNITIES"), 25),
            max_llm_refinements=_as_int(os.getenv("MAX_LLM_REFINEMENTS"), 10),
            use_browser_fallback=_as_bool(os.getenv("USE_BROWSER_FALLBACK"), True),
            smtp_probe_enabled=_as_bool(os.getenv("SMTP_PROBE_ENABLED"), False),
            min_email_validation_score=_as_int(
                os.getenv("MIN_EMAIL_VALIDATION_SCORE"),
                2,
            ),
            openai_enabled=_as_bool(os.getenv("OPENAI_ENABLED"), True),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip(),
            openai_reasoning_effort=os.getenv(
                "OPENAI_REASONING_EFFORT",
                "low",
            ).strip(),
            google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY", "").strip(),
            google_search_engine_id=os.getenv(
                "GOOGLE_SEARCH_ENGINE_ID",
                "",
            ).strip(),
            audit_backend=os.getenv("AUDIT_BACKEND", "firestore").strip().lower(),
            firestore_collection=os.getenv(
                "FIRESTORE_COLLECTION",
                "growth_engine_runs",
            ).strip(),
            firestore_profile_collection=os.getenv(
                "FIRESTORE_PROFILE_COLLECTION",
                "growth_engine_profiles",
            ).strip(),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)").strip(),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
            google_cloud_service_account_json_b64=os.getenv(
                "GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64",
                "",
            ).strip(),
            firebase_storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET", "").strip(),
            firebase_api_key=os.getenv("FIREBASE_API_KEY", "").strip(),
            firebase_auth_domain=os.getenv("FIREBASE_AUTH_DOMAIN", "").strip(),
            firebase_project_id=os.getenv("FIREBASE_PROJECT_ID", "").strip(),
            default_discovery_modes=_as_list(
                os.getenv("DEFAULT_DISCOVERY_MODES"),
                ["customers", "partners"],
            ),
            default_target_geographies=_as_list(
                os.getenv("DEFAULT_TARGET_GEOGRAPHIES"),
                ["India"],
            ),
        )
