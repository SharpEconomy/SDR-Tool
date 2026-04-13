from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from growth_engine.utils import normalize_whitespace
from growth_engine_web.runtime import get_runtime_settings

GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile")
GOOGLE_OAUTH_STATE_KEY = "growth_engine_google_oauth_state"


class GoogleAuthenticationError(RuntimeError):
    """Raised when Google OAuth sign-in fails."""


def _format_google_provider_error(
    payload: dict[str, Any],
    *,
    redirect_uri: str = "",
) -> str:
    error_code = normalize_whitespace(str(payload.get("error") or ""))
    error_description = normalize_whitespace(
        str(payload.get("error_description") or "")
    )
    normalized_redirect_uri = normalize_whitespace(redirect_uri)
    if error_code == "redirect_uri_mismatch" and normalized_redirect_uri:
        return (
            "Google sign-in failed: redirect_uri_mismatch. "
            f"Register this exact callback URI in Google Cloud Console: {normalized_redirect_uri}"
        )
    if not error_code and not error_description:
        return "Google sign-in could not be completed."
    details = ": ".join(part for part in (error_code, error_description) if part)
    return f"Google sign-in failed: {details}"


def google_auth_is_configured() -> bool:
    settings = get_runtime_settings()
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def create_google_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def build_google_oauth_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    normalized_client_id = normalize_whitespace(client_id)
    normalized_redirect_uri = normalize_whitespace(redirect_uri)
    normalized_state = normalize_whitespace(state)
    if not normalized_client_id:
        raise GoogleAuthenticationError("Google authentication is not configured.")
    if not normalized_redirect_uri:
        raise GoogleAuthenticationError("Google sign-in redirect is invalid.")
    if not normalized_state:
        raise GoogleAuthenticationError("Google sign-in state is invalid.")

    query = urlencode(
        {
            "client_id": normalized_client_id,
            "redirect_uri": normalized_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "state": normalized_state,
            "access_type": "online",
            "include_granted_scopes": "true",
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{query}"


def exchange_google_code(
    *,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    settings = get_runtime_settings()
    normalized_code = normalize_whitespace(code)
    normalized_redirect_uri = normalize_whitespace(redirect_uri)
    if not normalized_code:
        raise GoogleAuthenticationError(
            "Google sign-in did not return an authorization code."
        )
    if not google_auth_is_configured():
        raise GoogleAuthenticationError("Google authentication is not configured.")
    if not normalized_redirect_uri:
        raise GoogleAuthenticationError("Google sign-in redirect is invalid.")

    try:
        response = requests.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "code": normalized_code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": normalized_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=settings.request_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise GoogleAuthenticationError(
            "Google sign-in could not reach Google's token service."
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleAuthenticationError(
            "Google sign-in returned an invalid token response."
        ) from exc

    if not response.ok:
        raise GoogleAuthenticationError(
            _format_google_provider_error(
                payload,
                redirect_uri=normalized_redirect_uri,
            )
        )

    if not normalize_whitespace(str(payload.get("id_token") or "")):
        raise GoogleAuthenticationError("Google sign-in did not return an ID token.")

    return payload


def verify_google_id_token(token: str) -> dict[str, str]:
    settings = get_runtime_settings()
    normalized_token = normalize_whitespace(token)
    if not normalized_token:
        raise GoogleAuthenticationError("Missing Google ID token.")
    if not settings.google_oauth_client_id:
        raise GoogleAuthenticationError("Google authentication is not configured.")

    try:
        claims = id_token.verify_oauth2_token(
            normalized_token,
            google_requests.Request(),
            settings.google_oauth_client_id,
        )
    except Exception as exc:  # pragma: no cover - provider exceptions vary
        raise GoogleAuthenticationError(
            "Google sign-in could not be verified."
        ) from exc

    if not claims:
        raise GoogleAuthenticationError("Google sign-in could not be verified.")

    email = normalize_whitespace(str(claims.get("email") or ""))
    if not email:
        raise GoogleAuthenticationError("Google sign-in did not include an email.")

    email_verified = claims.get("email_verified")
    if email_verified is False or str(email_verified).strip().lower() == "false":
        raise GoogleAuthenticationError("Google sign-in requires a verified email.")

    return {
        "email": email,
        "uid": normalize_whitespace(str(claims.get("sub") or "")),
        "display_name": normalize_whitespace(str(claims.get("name") or "")),
        "login_at": datetime.now(UTC).isoformat(),
    }
