from __future__ import annotations

from hackindia_leads import config


def test_as_helpers_handle_defaults_and_parsing() -> None:
    assert config._as_bool("true", False) is True
    assert config._as_bool("off", True) is False
    assert config._as_bool(None, True) is True
    assert config._as_int("7", 1) == 7
    assert config._as_int("bad", 1) == 1
    assert config._as_list("ai, web3, , llm", ["x"]) == ["ai", "web3", "llm"]
    assert config._as_list("", ["x"]) == ["x"]


def test_settings_load_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_FROM_EMAIL", "team@example.com")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("MAX_EVENTS_PER_SOURCE", "4")
    monkeypatch.setenv("MAX_CONTACTS_PER_COMPANY", "8")
    monkeypatch.setenv("MAX_SOURCE_WORKERS", "3")
    monkeypatch.setenv("MAX_ENRICHMENT_WORKERS", "6")
    monkeypatch.setenv("DEFAULT_KEYWORDS", "ai, blockchain")
    monkeypatch.setenv("DEFAULT_SOURCES", "ethglobal,mlh")
    monkeypatch.setenv("USE_BROWSER_FALLBACK", "false")
    monkeypatch.setenv("WEBSITE_PRECHECK_REQUIRED", "false")
    monkeypatch.setenv("SMTP_PRECHECK_REQUIRED", "true")
    monkeypatch.setenv("MIN_VALIDATION_SCORE", "3")

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
