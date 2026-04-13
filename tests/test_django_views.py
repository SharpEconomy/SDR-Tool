from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from growth_engine_web.analytics import AdminAnalyticsSnapshot, AnalyticsMetric
from growth_engine_web.google_auth import (
    GOOGLE_OAUTH_STATE_KEY,
    GoogleAuthenticationError,
)
from growth_engine_web.session_state import (
    AUTH_USER_KEY,
    LEAD_RESULTS_KEY,
    POST_SAVE_REQUEST_NOTES_KEY,
    POST_SAVE_REQUESTED_DATA_KEY,
    PROFILE_DRAFT_KEY,
    PROFILE_RESEARCH_RESULT_KEY,
    PROFILE_SAVE_URI_KEY,
)
from growth_engine_web.views import APP_BOOT_ID
from tests.helpers import (
    build_draft_payload,
    build_intake_draft,
    build_research_result,
    build_research_result_payload,
    enable_google_auth,
    localhost_client,
)


def test_research_profile_stores_research_result_in_session(
    settings,
    monkeypatch,
) -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(business_name="Old Co")
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload(
        business_name="Old Co"
    )
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/old-profile"
    session[POST_SAVE_REQUESTED_DATA_KEY] = ["partners"]
    session[LEAD_RESULTS_KEY] = {"export_name": "old.xlsx"}
    session.save()
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
    assert PROFILE_SAVE_URI_KEY not in session
    assert POST_SAVE_REQUESTED_DATA_KEY not in session
    assert LEAD_RESULTS_KEY not in session


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
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/profile"
    session[LEAD_RESULTS_KEY] = {"export_name": "demo.xlsx"}
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
    assert client.session[PROFILE_SAVE_URI_KEY] is None
    assert LEAD_RESULTS_KEY not in client.session


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


def test_request_data_persists_follow_up_request(monkeypatch) -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(discovery_modes=["customers"])
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload()
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/profile"
    session.save()

    class _Engine:
        def __init__(self, settings) -> None:
            self.artifact_store = None
            self.audit_store = None

        def run(self, intake):
            return SimpleNamespace(
                opportunities=[
                    SimpleNamespace(
                        as_export_row=lambda: {
                            "priority_rank": 1,
                            "priority_score": 82,
                            "discovery_mode": "customers",
                            "entity_name": "Example Retail",
                            "entity_website": "https://example.com",
                            "location": "India",
                            "decision_maker": "Riya Sharma",
                            "decision_maker_email": "riya@example.com",
                            "contact_path": "riya@example.com",
                            "next_action": "Email the buyer",
                            "source_url": "https://example.com",
                        }
                    )
                ],
                skipped_entities=[
                    SimpleNamespace(
                        as_export_row=lambda: {
                            "entity_name": "Noise Listing",
                            "reason": "Excluded",
                        }
                    )
                ],
                export_name="demo.xlsx",
                export_bytes=b"excel-bytes",
            )

    monkeypatch.setattr("growth_engine_web.views.DecisionEngine", _Engine)
    response = client.post(
        "/request-data/",
        {
            "requested_data": ["customers", "partners"],
            "notes": "Only verified companies",
        },
    )

    assert response.status_code == 302
    assert client.session[POST_SAVE_REQUESTED_DATA_KEY] == ["customers", "partners"]
    assert client.session[LEAD_RESULTS_KEY]["export_name"] == "demo.xlsx"


def test_request_data_clears_previous_leads_before_new_generation(monkeypatch) -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(discovery_modes=["customers"])
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload()
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/profile"
    session[LEAD_RESULTS_KEY] = {"export_name": "old.xlsx"}
    session.save()

    class _Engine:
        def __init__(self, settings) -> None:
            self.artifact_store = None
            self.audit_store = None

        def run(self, intake):
            raise RuntimeError("engine exploded")

    monkeypatch.setattr("growth_engine_web.views.DecisionEngine", _Engine)

    response = client.post(
        "/request-data/",
        {"requested_data": ["customers"], "notes": "Only verified companies"},
    )

    assert response.status_code == 302
    assert LEAD_RESULTS_KEY not in client.session


def test_request_data_requires_saved_profile() -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(discovery_modes=["customers"])
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload()
    session.save()

    response = client.post(
        "/request-data/",
        {"requested_data": ["customers"], "notes": "Only verified companies"},
    )

    assert response.status_code == 302
    assert LEAD_RESULTS_KEY not in client.session


def test_download_leads_export_returns_workbook() -> None:
    client = localhost_client()
    session = client.session
    session[LEAD_RESULTS_KEY] = {
        "opportunity_rows": [],
        "skipped_rows": [],
        "export_name": "demo.xlsx",
        "export_payload_b64": "ZXhjZWwtcGF5bG9hZA==",
    }
    session.save()

    response = client.get("/leads/download/")

    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "demo.xlsx" in response["Content-Disposition"]
    assert response.content == b"excel-payload"


def test_google_login_redirects_to_google_and_stores_state(
    settings,
    monkeypatch,
) -> None:
    enable_google_auth(settings)
    client = localhost_client()

    monkeypatch.setattr(
        "growth_engine_web.views.create_google_oauth_state",
        lambda: "state-123",
    )

    response = client.get("/auth/google/")

    assert response.status_code == 302
    assert client.session[GOOGLE_OAUTH_STATE_KEY] == "state-123"

    parsed = urlparse(response["Location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["google-client-id"]
    assert query["state"] == ["state-123"]


def test_google_login_uses_configured_app_base_url_for_callback(
    settings,
    monkeypatch,
) -> None:
    enable_google_auth(settings)
    settings.app_base_url = "https://sdr.buidwithai.ai"
    client = localhost_client()

    monkeypatch.setattr(
        "growth_engine_web.views.create_google_oauth_state",
        lambda: "state-123",
    )

    response = client.get("/auth/google/")

    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    query = parse_qs(parsed.query)
    assert query["redirect_uri"][0] == "https://sdr.buidwithai.ai/auth/google/callback/"


def test_google_login_prefers_explicit_redirect_uri_from_settings(
    settings,
    monkeypatch,
) -> None:
    enable_google_auth(settings)
    settings.app_base_url = "https://wrong.example"
    settings.google_oauth_redirect_uri = (
        "https://sdr.buidwithai.ai/auth/google/callback/"
    )
    client = localhost_client()

    monkeypatch.setattr(
        "growth_engine_web.views.create_google_oauth_state",
        lambda: "state-123",
    )

    response = client.get("/auth/google/")

    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    query = parse_qs(parsed.query)
    assert query["redirect_uri"][0] == settings.google_oauth_redirect_uri


def test_google_login_redirects_home_when_auth_not_configured() -> None:
    client = localhost_client()

    response = client.get("/auth/google/")

    assert response.status_code == 302
    assert response["Location"] == "/"


def test_google_callback_stores_session_user(settings, monkeypatch) -> None:
    enable_google_auth(settings)
    client = localhost_client()
    session = client.session
    session[GOOGLE_OAUTH_STATE_KEY] = "state-123"
    session.save()

    monkeypatch.setattr(
        "growth_engine_web.views.exchange_google_code",
        lambda *, code, redirect_uri: {"id_token": "google-id-token"},
    )
    monkeypatch.setattr(
        "growth_engine_web.views.verify_google_id_token",
        lambda token: {
            "email": "user@example.com",
            "uid": "user-1",
            "display_name": "Example User",
            "login_at": "2026-04-12T00:00:00+00:00",
        },
    )

    response = client.get(
        "/auth/google/callback/",
        {"code": "auth-code", "state": "state-123"},
    )

    assert response.status_code == 302
    assert client.session[AUTH_USER_KEY]["email"] == "user@example.com"


def test_google_callback_rejects_state_mismatch(settings) -> None:
    enable_google_auth(settings)
    client = localhost_client()
    session = client.session
    session[GOOGLE_OAUTH_STATE_KEY] = "expected-state"
    session.save()

    response = client.get(
        "/auth/google/callback/",
        {"code": "auth-code", "state": "wrong-state"},
    )

    assert response.status_code == 302
    assert AUTH_USER_KEY not in client.session


def test_google_callback_handles_provider_error(settings, monkeypatch) -> None:
    enable_google_auth(settings)
    client = localhost_client()
    session = client.session
    session[GOOGLE_OAUTH_STATE_KEY] = "state-123"
    session.save()

    monkeypatch.setattr(
        "growth_engine_web.views.exchange_google_code",
        lambda *, code, redirect_uri: (_ for _ in ()).throw(
            GoogleAuthenticationError("Google sign-in could not be completed.")
        ),
    )

    response = client.get(
        "/auth/google/callback/",
        {"code": "auth-code", "state": "state-123"},
    )

    assert response.status_code == 302
    assert AUTH_USER_KEY not in client.session


def test_home_renders_sign_in_gate_when_auth_required(settings) -> None:
    enable_google_auth(settings)
    client = localhost_client()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Sign in before researching and saving profiles." in content
    assert "Sign in with Google" in content


def test_home_shows_admin_analytics_link_for_admin_user() -> None:
    client = localhost_client()
    session = client.session
    session[AUTH_USER_KEY] = {"email": "admin@example.com"}
    session["growth_engine_boot_id"] = APP_BOOT_ID
    session.save()

    response = client.get("/")

    assert response.status_code == 200
    assert "Admin analytics" in response.content.decode("utf-8")


def test_home_shows_signed_in_user_and_logout_for_session_user() -> None:
    client = localhost_client()
    session = client.session
    session[AUTH_USER_KEY] = {
        "email": "admin@example.com",
        "display_name": "Admin User",
    }
    session["growth_engine_boot_id"] = APP_BOOT_ID
    session.save()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Admin User" in content
    assert "admin@example.com" in content
    assert "Log out" in content


def test_home_shows_open_analytics_when_google_sign_in_is_disabled(
    settings,
) -> None:
    settings.google_sign_in_enabled = False
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"
    client = localhost_client()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Admin analytics" in content
    assert "Sign in with Google" not in content


def test_home_clears_stale_workspace_on_new_boot() -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload(business_name="Stale Co")
    session["growth_engine_boot_id"] = "old-boot-id"
    session.save()

    response = client.get("/")

    assert response.status_code == 200
    assert PROFILE_DRAFT_KEY not in client.session
    assert client.session["growth_engine_boot_id"] == APP_BOOT_ID


def test_home_renders_locked_accordions_after_save_and_lead_generation() -> None:
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload()
    session[PROFILE_RESEARCH_RESULT_KEY] = build_research_result_payload()
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/profile"
    session[POST_SAVE_REQUESTED_DATA_KEY] = ["customers", "partners"]
    session[POST_SAVE_REQUEST_NOTES_KEY] = "Focus on verified buyers"
    session[LEAD_RESULTS_KEY] = {
        "opportunity_rows": [
            {
                "priority_rank": 1,
                "priority_score": 82,
                "discovery_mode": "customers",
                "entity_name": "Example Retail",
                "entity_website": "https://example.com",
                "location": "India",
                "decision_maker": "Riya Sharma",
                "decision_maker_email": "riya@example.com",
                "contact_path": "riya@example.com",
                "next_action": "Email the buyer",
                "source_url": "https://example.com",
                "why_it_matters": "High-fit retail buyer with active demand.",
            }
        ],
        "skipped_rows": [],
        "export_name": "demo.xlsx",
        "export_payload_b64": "ZXhjZWwtcGF5bG9hZA==",
    }
    session["growth_engine_boot_id"] = APP_BOOT_ID
    session.save()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Research ready" in content
    assert "Submitted" in content
    assert "Confirmed" in content
    assert "Verified" in content
    assert "Requested" in content
    assert "locked for review" in content
    assert "Prioritized leads" in content
    assert "Rank 1" in content
    assert "<table" not in content


def test_analytics_dashboard_requires_admin_access() -> None:
    client = localhost_client()

    response = client.get("/admin/analytics/")

    assert response.status_code == 302
    assert response["Location"] == "/"


def test_analytics_dashboard_renders_for_allowlisted_admin(monkeypatch) -> None:
    client = localhost_client()
    session = client.session
    session[AUTH_USER_KEY] = {
        "email": "admin@example.com",
        "display_name": "Admin User",
    }
    session["growth_engine_boot_id"] = APP_BOOT_ID
    session.save()

    monkeypatch.setattr(
        "growth_engine_web.views.build_admin_analytics_snapshot",
        lambda settings: AdminAnalyticsSnapshot(
            metrics=[
                AnalyticsMetric(
                    label="Confirmed profiles",
                    value="12",
                    detail="Profiles saved to the Firestore workspace.",
                )
            ],
            recent_profiles=[
                {
                    "business_name": "Demo Co",
                    "industry": "Software",
                    "location": "Mumbai, India",
                    "confirmed_by": "admin@example.com",
                    "confirmed_at": "2026-04-13 10:00 UTC",
                    "discovery_modes": "Customers, Partners",
                }
            ],
            recent_runs=[
                {
                    "business_name": "Demo Co",
                    "created_at": "2026-04-13 10:30 UTC",
                    "discovery_modes": "Customers",
                    "opportunity_count": "4",
                    "skipped_count": "2",
                    "export_name": "demo.xlsx",
                }
            ],
            discovery_breakdown=[{"label": "Customers", "count": 8, "width": 100}],
            industry_breakdown=[{"label": "Software", "count": 5, "width": 100}],
            availability_notes=["Audit analytics are available."],
        ),
    )

    response = client.get("/admin/analytics/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Workspace analytics" in content
    assert "Confirmed profiles" in content
    assert "Demo Co" in content
    assert "Run ledger" in content
    assert "Admin User" in content
    assert "Log out" in content


def test_analytics_dashboard_skips_admin_verification_when_google_sign_in_is_disabled(
    settings,
    monkeypatch,
) -> None:
    settings.google_sign_in_enabled = False
    client = localhost_client()

    monkeypatch.setattr(
        "growth_engine_web.views.build_admin_analytics_snapshot",
        lambda settings: AdminAnalyticsSnapshot(
            metrics=[],
            recent_profiles=[],
            recent_runs=[],
            discovery_breakdown=[],
            industry_breakdown=[],
            availability_notes=[],
        ),
    )

    response = client.get("/admin/analytics/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Workspace analytics" in content
    assert "Open workspace session" in content
    assert "Log out" not in content


def test_research_profile_requires_auth_when_google_auth_is_enabled(
    settings,
    monkeypatch,
) -> None:
    enable_google_auth(settings)
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


def test_research_profile_does_not_require_auth_when_google_sign_in_is_disabled(
    settings,
    monkeypatch,
) -> None:
    settings.google_sign_in_enabled = False
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"
    client = localhost_client()
    result = build_research_result()

    monkeypatch.setattr(
        "growth_engine_web.views.BusinessProfileResearcher.research",
        lambda self, *, business_name, website: result,
    )

    response = client.post(
        "/research/",
        {"business_name": "Demo Co", "website": "demo.example"},
    )

    assert response.status_code == 302
    assert client.session[PROFILE_DRAFT_KEY]["business_name"] == "Demo Co"


def test_save_profile_requires_auth_when_google_auth_is_enabled(settings) -> None:
    enable_google_auth(settings)
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


def test_save_profile_does_not_require_auth_when_google_sign_in_is_disabled(
    settings,
    monkeypatch,
) -> None:
    settings.google_sign_in_enabled = False
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"
    client = localhost_client()
    session = client.session
    session[PROFILE_DRAFT_KEY] = build_draft_payload()
    session[PROFILE_RESEARCH_RESULT_KEY] = {
        "draft": session[PROFILE_DRAFT_KEY],
        "sources": [],
        "verification_summary": "Verified from website and search results.",
    }
    session.save()

    monkeypatch.setattr(
        "growth_engine_web.views.FirestoreProfileStore.save",
        lambda self, document_id, payload: f"firestore://demo/{document_id}",
    )

    response = client.post("/save/")

    assert response.status_code == 302
    assert client.session[PROFILE_SAVE_URI_KEY].startswith("firestore://demo/")


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
