from __future__ import annotations

import pytest

from growth_engine_web.firebase_auth import (
    FirebaseAuthenticationError,
    verify_firebase_login,
)


def test_verify_firebase_login_returns_normalized_user(settings, monkeypatch) -> None:
    settings.firebase_project_id = "demo-project"

    monkeypatch.setattr(
        "growth_engine_web.firebase_auth.id_token.verify_firebase_token",
        lambda token, request, project_id: {
            "email": "  user@example.com ",
            "uid": "user-123",
            "name": " Example User ",
        },
    )

    user = verify_firebase_login(" firebase-token ")

    assert user["email"] == "user@example.com"
    assert user["uid"] == "user-123"
    assert user["display_name"] == "Example User"
    assert "login_at" in user


def test_verify_firebase_login_uses_sub_when_uid_missing(
    settings,
    monkeypatch,
) -> None:
    settings.firebase_project_id = "demo-project"

    monkeypatch.setattr(
        "growth_engine_web.firebase_auth.id_token.verify_firebase_token",
        lambda token, request, project_id: {
            "email": "user@example.com",
            "sub": "sub-123",
            "name": "Example User",
        },
    )

    user = verify_firebase_login("firebase-token")

    assert user["uid"] == "sub-123"


def test_verify_firebase_login_requires_token() -> None:
    with pytest.raises(FirebaseAuthenticationError) as exc_info:
        verify_firebase_login("   ")

    assert str(exc_info.value) == "Missing Firebase ID token."


def test_verify_firebase_login_requires_project_id(settings) -> None:
    settings.firebase_project_id = ""

    with pytest.raises(FirebaseAuthenticationError) as exc_info:
        verify_firebase_login("firebase-token")

    assert str(exc_info.value) == "Firebase authentication is not configured."


def test_verify_firebase_login_wraps_provider_errors(settings, monkeypatch) -> None:
    settings.firebase_project_id = "demo-project"

    def _raise(*args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "growth_engine_web.firebase_auth.id_token.verify_firebase_token",
        _raise,
    )

    with pytest.raises(FirebaseAuthenticationError) as exc_info:
        verify_firebase_login("firebase-token")

    assert str(exc_info.value) == "Firebase sign-in could not be verified."


def test_verify_firebase_login_requires_email(settings, monkeypatch) -> None:
    settings.firebase_project_id = "demo-project"

    monkeypatch.setattr(
        "growth_engine_web.firebase_auth.id_token.verify_firebase_token",
        lambda token, request, project_id: {"uid": "user-123"},
    )

    with pytest.raises(FirebaseAuthenticationError) as exc_info:
        verify_firebase_login("firebase-token")

    assert str(exc_info.value) == "Firebase sign-in did not include an email."
