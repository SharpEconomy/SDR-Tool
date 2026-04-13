from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests

from growth_engine.config import Settings
from growth_engine_web.google_auth import (
    GoogleAuthenticationError,
    build_google_oauth_authorization_url,
    exchange_google_code,
    verify_google_id_token,
)


def test_build_google_oauth_authorization_url_contains_required_parameters() -> None:
    url = build_google_oauth_authorization_url(
        client_id="google-client-id",
        redirect_uri="http://localhost:8000/auth/google/callback/",
        state="state-123",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["google-client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/google/callback/"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert query["state"] == ["state-123"]


def test_exchange_google_code_returns_token_payload(settings, monkeypatch) -> None:
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"

    class _Response:
        ok = True

        @staticmethod
        def json():
            return {"id_token": "google-id-token", "access_token": "access-token"}

    monkeypatch.setattr(
        "growth_engine_web.google_auth.requests.post",
        lambda *args, **kwargs: _Response(),
    )

    payload = exchange_google_code(
        code="auth-code",
        redirect_uri="http://localhost:8000/auth/google/callback/",
    )

    assert payload["id_token"] == "google-id-token"


def test_exchange_google_code_wraps_network_errors(settings, monkeypatch) -> None:
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"

    def _raise(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("growth_engine_web.google_auth.requests.post", _raise)

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        exchange_google_code(
            code="auth-code",
            redirect_uri="http://localhost:8000/auth/google/callback/",
        )

    assert (
        str(exc_info.value) == "Google sign-in could not reach Google's token service."
    )


def test_exchange_google_code_requires_id_token(settings, monkeypatch) -> None:
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"

    class _Response:
        ok = True

        @staticmethod
        def json():
            return {"access_token": "access-token"}

    monkeypatch.setattr(
        "growth_engine_web.google_auth.requests.post",
        lambda *args, **kwargs: _Response(),
    )

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        exchange_google_code(
            code="auth-code",
            redirect_uri="http://localhost:8000/auth/google/callback/",
        )

    assert str(exc_info.value) == "Google sign-in did not return an ID token."


def test_exchange_google_code_surfaces_provider_error_details(
    settings,
    monkeypatch,
) -> None:
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"

    class _Response:
        ok = False

        @staticmethod
        def json():
            return {
                "error": "redirect_uri_mismatch",
                "error_description": "The redirect URI did not match.",
            }

    monkeypatch.setattr(
        "growth_engine_web.google_auth.requests.post",
        lambda *args, **kwargs: _Response(),
    )

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        exchange_google_code(
            code="auth-code",
            redirect_uri="http://localhost:8000/auth/google/callback/",
        )

    assert "redirect_uri_mismatch" in str(exc_info.value)
    assert "http://localhost:8000/auth/google/callback/" in str(exc_info.value)


def test_verify_google_id_token_returns_normalized_user(settings, monkeypatch) -> None:
    settings.google_oauth_client_id = "google-client-id"

    monkeypatch.setattr(
        "growth_engine_web.google_auth.id_token.verify_oauth2_token",
        lambda token, request, client_id: {
            "email": "  user@example.com ",
            "email_verified": True,
            "sub": "user-123",
            "name": " Example User ",
        },
    )

    user = verify_google_id_token(" google-id-token ")

    assert user["email"] == "user@example.com"
    assert user["uid"] == "user-123"
    assert user["display_name"] == "Example User"
    assert "login_at" in user


def test_verify_google_id_token_requires_configured_client_id(settings) -> None:
    settings.google_oauth_client_id = ""

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        verify_google_id_token("google-id-token")

    assert str(exc_info.value) == "Google authentication is not configured."


def test_verify_google_id_token_wraps_provider_errors(settings, monkeypatch) -> None:
    settings.google_oauth_client_id = "google-client-id"

    def _raise(*args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "growth_engine_web.google_auth.id_token.verify_oauth2_token",
        _raise,
    )

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        verify_google_id_token("google-id-token")

    assert str(exc_info.value) == "Google sign-in could not be verified."


def test_verify_google_id_token_requires_verified_email(
    settings,
    monkeypatch,
) -> None:
    settings.google_oauth_client_id = "google-client-id"

    monkeypatch.setattr(
        "growth_engine_web.google_auth.id_token.verify_oauth2_token",
        lambda token, request, client_id: {
            "email": "user@example.com",
            "email_verified": False,
            "sub": "user-123",
        },
    )

    with pytest.raises(GoogleAuthenticationError) as exc_info:
        verify_google_id_token("google-id-token")

    assert str(exc_info.value) == "Google sign-in requires a verified email."


def test_settings_load_supports_legacy_google_client_env_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        "growth_engine.config._load_env_values",
        lambda: {
            "GOOGLE_CLIENT_ID": "legacy-google-client-id",
            "GOOGLE_CLIENT_SECRET": "legacy-google-client-secret",
        },
    )

    settings = Settings.load()

    assert settings.google_oauth_client_id == "legacy-google-client-id"
    assert settings.google_oauth_client_secret == "legacy-google-client-secret"


def test_settings_load_supports_google_oauth_redirect_uri(monkeypatch) -> None:
    monkeypatch.setattr(
        "growth_engine.config._load_env_values",
        lambda: {
            "GOOGLE_OAUTH_REDIRECT_URI": (
                "https://sdr.buidwithai.ai/auth/google/callback/"
            ),
        },
    )

    settings = Settings.load()

    assert (
        settings.google_oauth_redirect_uri
        == "https://sdr.buidwithai.ai/auth/google/callback/"
    )
