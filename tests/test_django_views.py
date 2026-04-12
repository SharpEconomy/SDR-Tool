from __future__ import annotations

import json

from growth_engine_web.firebase_auth import FirebaseAuthenticationError
from growth_engine_web.session_state import (
    AUTH_USER_KEY,
    POST_SAVE_REQUESTED_DATA_KEY,
    PROFILE_DRAFT_KEY,
    PROFILE_RESEARCH_RESULT_KEY,
    PROFILE_SAVE_URI_KEY,
)
from tests.helpers import (
    build_draft_payload,
    build_intake_draft,
    build_research_result,
    build_research_result_payload,
    enable_firebase_auth,
    localhost_client,
)


def test_research_profile_stores_research_result_in_session(
    settings,
    monkeypatch,
) -> None:
    client = localhost_client()
    result = build_research_result(
        draft=build_intake_draft(discovery_modes=["customers"])
    )
    monkeypatch.setattr(
        "growth_engine_web.views.BusinessProfileResearcher.research",
        lambda self, *, business_name, website: result,
    )

    response = client.post(
        "/research/",
        {"business_name": "Demo Co", "website": "demo.example"},
    )

    assert response.status_code == 302
    session = client.session
    assert session[PROFILE_DRAFT_KEY]["business_name"] == "Demo Co"
    assert session[PROFILE_RESEARCH_RESULT_KEY]["verification_summary"].startswith(
        "Verified"
    )


def test_edit_section_updates_session_draft() -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(
        description="Old description",
        target_geographies=[],
        budget="",
        ideal_customer_profile="",
        preferred_company_sizes=[],
        preferred_sectors=[],
        offerings=[],
        goals=[],
        opportunity_type_needed="",
        inclusion_keywords=[],
        vendor_constraints="",
        supplier_constraints="",
        user_urls=[],
    )
    session[PROFILE_RESEARCH_RESULT_KEY] = {
        "draft": session[PROFILE_DRAFT_KEY],
        "sources": [],
        "verification_summary": "Summary",
    }
    session.save()

    response = client.post(
        "/edit/business_snapshot/",
        {
            "description": "New description",
            "industry": "AI software",
            "location": "Mumbai, India",
            "website": "https://demo.example",
        },
    )

    assert response.status_code == 302
    assert client.session[PROFILE_DRAFT_KEY]["description"] == "New description"
    assert (
        client.session[PROFILE_RESEARCH_RESULT_KEY]["draft"]["industry"]
        == "AI software"
    )


def test_save_profile_writes_firestore_uri_to_session(settings, monkeypatch) -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload()
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload()
    session[AUTH_USER_KEY] = {"email": "user@example.com"}
    session.save()

    monkeypatch.setattr(
        "growth_engine_web.views.FirestoreProfileStore.save",
        lambda self, document_id, payload: f"firestore://demo/{document_id}",
    )

    response = client.post("/save/")

    assert response.status_code == 302
    assert client.session[PROFILE_SAVE_URI_KEY].startswith("firestore://demo/")


def test_request_data_persists_follow_up_request() -> None:
    client = localhost_client()

    response = client.post(
        "/request-data/",
        {
            "requested_data": ["customers", "partners"],
            "notes": "Only verified companies",
        },
    )

    assert response.status_code == 302
    assert client.session[POST_SAVE_REQUESTED_DATA_KEY] == ["customers", "partners"]


def test_firebase_login_stores_session_user(settings, monkeypatch) -> None:
    enable_firebase_auth(settings)
    client = localhost_client(enforce_csrf_checks=False)

    monkeypatch.setattr(
        "growth_engine_web.views.verify_firebase_login",
        lambda token: {
            "email": "user@example.com",
            "uid": "user-1",
            "display_name": "Example User",
            "login_at": "2026-04-12T00:00:00+00:00",
        },
    )

    response = client.post(
        "/auth/firebase/",
        data=json.dumps({"token": "firebase-token"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert client.session[AUTH_USER_KEY]["email"] == "user@example.com"


def test_firebase_login_rejects_invalid_json(settings) -> None:
    enable_firebase_auth(settings)
    client = localhost_client(enforce_csrf_checks=False)

    response = client.post(
        "/auth/firebase/",
        data="{invalid",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid login payload."


def test_firebase_login_rejects_when_auth_not_configured() -> None:
    client = localhost_client(enforce_csrf_checks=False)

    response = client.post(
        "/auth/firebase/",
        data=json.dumps({"token": "firebase-token"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Firebase authentication is not configured."


def test_firebase_login_returns_unauthorized_on_verification_error(
    settings,
    monkeypatch,
) -> None:
    enable_firebase_auth(settings)
    client = localhost_client(enforce_csrf_checks=False)

    monkeypatch.setattr(
        "growth_engine_web.views.verify_firebase_login",
        lambda token: (_ for _ in ()).throw(
            FirebaseAuthenticationError("Firebase sign-in could not be verified.")
        ),
    )

    response = client.post(
        "/auth/firebase/",
        data=json.dumps({"token": "firebase-token"}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"] == "Firebase sign-in could not be verified."


def test_home_renders_sign_in_gate_when_auth_required(settings) -> None:
    enable_firebase_auth(settings)
    client = localhost_client()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Sign in before researching and saving profiles." in content
    assert "Sign in with Google" in content


def test_research_profile_requires_auth_when_firebase_is_enabled(
    settings,
    monkeypatch,
) -> None:
    enable_firebase_auth(settings)
    client = localhost_client()

    monkeypatch.setattr(
        "growth_engine_web.views.BusinessProfileResearcher.research",
        lambda self, *, business_name, website: (_ for _ in ()).throw(
            AssertionError("research should not run")
        ),
    )

    response = client.post(
        "/research/",
        {"business_name": "Demo Co", "website": "demo.example"},
    )

    assert response.status_code == 302
    assert PROFILE_DRAFT_KEY not in client.session


def test_save_profile_requires_auth_when_firebase_is_enabled(settings) -> None:
    enable_firebase_auth(settings)
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload()
    session[PROFILE_RESEARCH_RESULT_KEY] = {
        "draft": session[PROFILE_DRAFT_KEY],
        "sources": [],
        "verification_summary": "Verified from website and search results.",
    }
    session.save()

    response = client.post("/save/")

    assert response.status_code == 302
    assert PROFILE_SAVE_URI_KEY not in client.session


def test_save_profile_redirects_when_research_state_is_missing() -> None:
    client = localhost_client()

    response = client.post("/save/")

    assert response.status_code == 302
    assert PROFILE_SAVE_URI_KEY not in client.session


def test_logout_clears_workspace_and_auth_state() -> None:
    client = localhost_client()
    session = client.session
    session[AUTH_USER_KEY] = {"email": "user@example.com"}
    session[PROFILE_DRAFT_KEY] = {"business_name": "Demo Co"}
    session.save()

    response = client.post("/auth/logout/")

    assert response.status_code == 302
    assert AUTH_USER_KEY not in client.session
    assert PROFILE_DRAFT_KEY not in client.session
