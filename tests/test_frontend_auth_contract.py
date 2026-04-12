from __future__ import annotations

from pathlib import Path


def test_firebase_auth_script_supports_local_redirect_and_popup_fallback() -> None:
    script = Path(
        "growth_engine_web/static/growth_engine_web/firebase-auth.js"
    ).read_text(encoding="utf-8")

    assert 'meta[name="server-authenticated"]' in script
    assert 'host === "localhost"' in script
    assert "onAuthStateChanged" in script
    assert "signInWithRedirect" in script
    assert "getRedirectResult" in script
    assert "signInWithPopup" in script
    assert "auth/popup-closed-by-user" in script
    assert 'fetch("/auth/firebase/"' in script


def test_base_template_exposes_server_authenticated_meta_tag() -> None:
    template = Path(
        "growth_engine_web/templates/growth_engine_web/base.html"
    ).read_text(encoding="utf-8")

    assert 'meta name="server-authenticated"' in template
    assert "request.session.growth_engine_auth_user" in template
