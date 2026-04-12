from __future__ import annotations

from datetime import UTC, datetime

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from growth_engine.utils import normalize_whitespace
from growth_engine_web.runtime import get_runtime_settings


class FirebaseAuthenticationError(RuntimeError):
    """Raised when Firebase sign-in verification fails."""


def verify_firebase_login(token: str) -> dict[str, str]:
    settings = get_runtime_settings()
    normalized_token = normalize_whitespace(token)
    if not normalized_token:
        raise FirebaseAuthenticationError("Missing Firebase ID token.")
    if not settings.firebase_project_id:
        raise FirebaseAuthenticationError("Firebase authentication is not configured.")

    try:
        claims = id_token.verify_firebase_token(
            normalized_token,
            google_requests.Request(),
            settings.firebase_project_id,
        )
    except Exception as exc:  # pragma: no cover - provider exceptions vary
        raise FirebaseAuthenticationError(
            "Firebase sign-in could not be verified."
        ) from exc

    if not claims:
        raise FirebaseAuthenticationError("Firebase sign-in could not be verified.")

    email = normalize_whitespace(str(claims.get("email") or ""))
    if not email:
        raise FirebaseAuthenticationError("Firebase sign-in did not include an email.")

    return {
        "email": email,
        "uid": normalize_whitespace(str(claims.get("uid") or claims.get("sub") or "")),
        "display_name": normalize_whitespace(str(claims.get("name") or "")),
        "login_at": datetime.now(UTC).isoformat(),
    }
