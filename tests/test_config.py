from __future__ import annotations

import pytest

from hackindia_leads import config


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        ("true", False, True),
        ("off", True, False),
        (None, True, True),
    ],
)
def test_as_bool_handles_defaults_and_parsing(
    value: str | None, default: bool, expected: bool
) -> None:
    assert config._as_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        ("7", 1, 7),
        ("bad", 1, 1),
    ],
)
def test_as_int_handles_defaults_and_parsing(
    value: str | None, default: int, expected: int
) -> None:
    assert config._as_int(value, default) == expected


def test_as_list_handles_defaults_and_parsing() -> None:
    assert config._as_list("ai, web3, , llm", ["x"]) == ["ai", "web3", "llm"]
    assert config._as_list("", ["x"]) == ["x"]


def test_settings_load_reads_env(monkeypatch) -> None:
    env_values = {
        "SMTP_FROM_EMAIL": "team@example.com",
        "REQUEST_TIMEOUT_SECONDS": "12",
        "SMTP_TIMEOUT_SECONDS": "9",
        "MAX_EVENTS_PER_SOURCE": "4",
        "MAX_CONTACTS_PER_COMPANY": "8",
        "MAX_SOURCE_WORKERS": "3",
        "MAX_ENRICHMENT_WORKERS": "6",
        "DEFAULT_KEYWORDS": "ai, blockchain",
        "DEFAULT_SOURCES": "ethglobal,mlh",
        "USE_BROWSER_FALLBACK": "false",
        "WEBSITE_PRECHECK_REQUIRED": "false",
        "SMTP_PRECHECK_REQUIRED": "true",
        "MIN_VALIDATION_SCORE": "3",
        "QUALIFICATION_ENABLED": "false",
        "USE_OPENAI_QUALIFICATION": "false",
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_MODEL": "gpt-5.4-mini",
        "QUALIFICATION_RECENT_MONTHS": "5",
        "QUALIFICATION_PREFERRED_RECENT_MONTHS": "2",
        "GOOGLE_SEARCH_API_KEY": "google-key",
        "GOOGLE_SEARCH_ENGINE_ID": "search-engine-id",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    loaded = config.Settings.load()

    assert loaded.smtp_from_email == "team@example.com"
    assert loaded.request_timeout_seconds == 12
    assert loaded.smtp_timeout_seconds == 9
    assert loaded.max_events_per_source == 4
    assert loaded.max_contacts_per_company == 8
    assert loaded.max_source_workers == 3
    assert loaded.max_enrichment_workers == 6
    assert loaded.default_keywords == ["ai", "blockchain"]
    assert loaded.default_sources == ["ethglobal", "mlh"]
    assert loaded.use_browser_fallback is False
    assert loaded.website_precheck_required is False
    assert loaded.smtp_precheck_required is True
    assert loaded.min_validation_score == 3
    assert loaded.qualification_enabled is False
    assert loaded.use_openai_qualification is False
    assert loaded.openai_api_key == "openai-key"
    assert loaded.openai_model == "gpt-5.4-mini"
    assert loaded.qualification_recent_months == 5
    assert loaded.qualification_preferred_recent_months == 2
    assert loaded.google_search_api_key == "google-key"
    assert loaded.google_search_engine_id == "search-engine-id"
