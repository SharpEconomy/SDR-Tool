from __future__ import annotations

from growth_engine_django import settings as django_settings


def test_allowed_hosts_include_the_live_domain_by_default() -> None:
    assert "localhost" in django_settings.ALLOWED_HOSTS
    assert "127.0.0.1" in django_settings.ALLOWED_HOSTS
    assert "testserver" in django_settings.ALLOWED_HOSTS
    assert "sdr.think-verse.com" in django_settings.ALLOWED_HOSTS


def test_as_list_merges_environment_hosts_without_dropping_defaults() -> None:
    assert django_settings._as_list(
        "localhost,127.0.0.1,sdr.builwithai.ai",
        ["localhost", "127.0.0.1", "testserver", "sdr.think-verse.com"],
    ) == [
        "localhost",
        "127.0.0.1",
        "testserver",
        "sdr.think-verse.com",
        "sdr.builwithai.ai",
    ]


def test_static_files_are_configured_for_production_delivery() -> None:
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in django_settings.MIDDLEWARE
    assert django_settings.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )
