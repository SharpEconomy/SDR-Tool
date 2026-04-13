from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


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


def _first_present(env: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = env.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _load_env_values() -> dict[str, str]:
    merged: dict[str, str] = {}
    for env_path in (Path(".env.example"), Path(".env")):
        if not env_path.exists():
            continue
        merged.update(
            {
                key: value
                for key, value in dotenv_values(env_path).items()
                if key and value is not None
            }
        )
    merged.update(
        {key: value for key, value in os.environ.items() if value is not None}
    )
    return merged


@dataclass(slots=True)
class Settings:
    app_name: str
    app_base_url: str
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
    google_sign_in_enabled: bool
    google_oauth_client_id: str
    google_oauth_client_secret: str
    google_oauth_redirect_uri: str
    admin_emails: list[str]
    default_discovery_modes: list[str]
    default_target_geographies: list[str]

    @classmethod
    def load(cls) -> "Settings":
        env = _load_env_values()
        return cls(
            app_name=str(
                env.get("APP_NAME", "Growth Opportunity Decision Engine")
            ).strip(),
            app_base_url=_first_present(env, "APP_BASE_URL", "PUBLIC_BASE_URL"),
            request_timeout_seconds=_as_int(env.get("REQUEST_TIMEOUT_SECONDS"), 20),
            request_retry_attempts=_as_int(env.get("REQUEST_RETRY_ATTEMPTS"), 2),
            request_retry_backoff_seconds=_as_int(
                env.get("REQUEST_RETRY_BACKOFF_SECONDS"),
                1,
            ),
            smtp_timeout_seconds=_as_int(env.get("SMTP_TIMEOUT_SECONDS"), 10),
            max_fetch_workers=_as_int(env.get("MAX_FETCH_WORKERS"), 6),
            max_validation_workers=_as_int(env.get("MAX_VALIDATION_WORKERS"), 4),
            max_results_per_adapter=_as_int(env.get("MAX_RESULTS_PER_ADAPTER"), 5),
            max_opportunities=_as_int(env.get("MAX_OPPORTUNITIES"), 25),
            max_llm_refinements=_as_int(env.get("MAX_LLM_REFINEMENTS"), 10),
            use_browser_fallback=_as_bool(env.get("USE_BROWSER_FALLBACK"), True),
            smtp_probe_enabled=_as_bool(env.get("SMTP_PROBE_ENABLED"), False),
            min_email_validation_score=_as_int(
                env.get("MIN_EMAIL_VALIDATION_SCORE"),
                2,
            ),
            openai_enabled=_as_bool(env.get("OPENAI_ENABLED"), True),
            openai_api_key=str(env.get("OPENAI_API_KEY", "")).strip(),
            openai_model=str(env.get("OPENAI_MODEL", "gpt-5.4-mini")).strip(),
            openai_reasoning_effort=str(
                env.get("OPENAI_REASONING_EFFORT", "low")
            ).strip(),
            google_search_api_key=str(env.get("GOOGLE_SEARCH_API_KEY", "")).strip(),
            google_search_engine_id=str(env.get("GOOGLE_SEARCH_ENGINE_ID", "")).strip(),
            audit_backend=str(env.get("AUDIT_BACKEND", "firestore")).strip().lower(),
            firestore_collection=str(
                env.get("FIRESTORE_COLLECTION", "growth_engine_runs")
            ).strip(),
            firestore_profile_collection=str(
                env.get("FIRESTORE_PROFILE_COLLECTION", "growth_engine_profiles")
            ).strip(),
            firestore_database=str(env.get("FIRESTORE_DATABASE", "(default)")).strip(),
            google_cloud_project=str(env.get("GOOGLE_CLOUD_PROJECT", "")).strip(),
            google_cloud_service_account_json_b64=str(
                env.get("GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64", "")
            ).strip(),
            google_sign_in_enabled=_as_bool(
                env.get("GOOGLE_SIGN_IN_ENABLED"),
                True,
            ),
            google_oauth_client_id=_first_present(
                env,
                "GOOGLE_OAUTH_CLIENT_ID",
                "GOOGLE_CLIENT_ID",
            ),
            google_oauth_client_secret=_first_present(
                env,
                "GOOGLE_OAUTH_CLIENT_SECRET",
                "GOOGLE_CLIENT_SECRET",
            ),
            google_oauth_redirect_uri=_first_present(
                env,
                "GOOGLE_OAUTH_REDIRECT_URI",
                "GOOGLE_REDIRECT_URI",
            ),
            admin_emails=_as_list(env.get("ADMIN_EMAILS"), []),
            default_discovery_modes=_as_list(
                env.get("DEFAULT_DISCOVERY_MODES"),
                ["customers", "partners"],
            ),
            default_target_geographies=_as_list(
                env.get("DEFAULT_TARGET_GEOGRAPHIES"),
                ["India"],
            ),
        )
