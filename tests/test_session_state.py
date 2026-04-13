from __future__ import annotations

from growth_engine.models import ProfileResearchResult, ResearchSource
from growth_engine_web.session_state import (
    AUTH_USER_KEY,
    BUSINESS_NAME_INPUT_KEY,
    LEAD_RESULTS_KEY,
    POST_SAVE_REQUEST_NOTES_KEY,
    POST_SAVE_REQUESTED_DATA_KEY,
    PROFILE_DRAFT_KEY,
    PROFILE_RESEARCH_RESULT_KEY,
    PROFILE_SAVE_URI_KEY,
    clear_lead_results,
    clear_workspace_state,
    deserialize_research_result,
    get_auth_user,
    get_draft,
    get_lead_export_bytes,
    get_lead_results,
    get_post_save_request,
    get_research_result,
    serialize_research_result,
    set_auth_user,
    set_draft,
    set_lead_results,
    set_post_save_request,
    set_research_result,
)
from tests.helpers import build_intake_draft, build_research_result, localhost_client


def test_research_result_serialization_round_trips() -> None:
    result = ProfileResearchResult(
        draft=build_intake_draft(discovery_modes=["customers"]),
        sources=[
            ResearchSource(
                kind="website",
                url="https://demo.example",
                title="Demo",
                snippet="Analytics platform",
            )
        ],
        verification_summary="Verified from public evidence.",
    )

    payload = serialize_research_result(result)
    restored = deserialize_research_result(payload)

    assert restored == result


def test_session_helpers_store_and_read_draft_result_and_user() -> None:
    session = localhost_client().session
    draft = build_intake_draft(discovery_modes=["customers"])
    result = build_research_result(
        draft=draft, sources=[], verification_summary="Verified"
    )

    set_draft(session, draft)
    set_research_result(session, result)
    set_auth_user(session, {"email": "user@example.com"})

    assert get_draft(session) == draft
    assert get_research_result(session) == result
    assert get_auth_user(session) == {"email": "user@example.com"}


def test_post_save_request_helpers_round_trip() -> None:
    session = localhost_client().session

    set_post_save_request(
        session,
        requested_data=["customers", "partners"],
        notes="Only verified companies",
    )

    assert get_post_save_request(session) == {
        "requested_data": ["customers", "partners"],
        "notes": "Only verified companies",
    }


def test_lead_result_helpers_round_trip() -> None:
    session = localhost_client().session

    set_lead_results(
        session,
        opportunity_rows=[{"entity_name": "Example Retail", "priority_rank": 1}],
        skipped_rows=[{"entity_name": "Noise Listing"}],
        export_name="demo.xlsx",
        export_bytes=b"excel-payload",
    )

    assert get_lead_results(session) == {
        "opportunity_rows": [{"entity_name": "Example Retail", "priority_rank": 1}],
        "skipped_rows": [{"entity_name": "Noise Listing"}],
        "export_name": "demo.xlsx",
        "export_payload_b64": "ZXhjZWwtcGF5bG9hZA==",
    }
    assert get_lead_export_bytes(session) == b"excel-payload"


def test_clear_lead_results_removes_cached_export() -> None:
    session = localhost_client().session
    session[LEAD_RESULTS_KEY] = {"export_name": "demo.xlsx"}
    session.save()

    clear_lead_results(session)

    assert LEAD_RESULTS_KEY not in session


def test_clear_workspace_state_preserves_auth_by_default() -> None:
    session = localhost_client().session
    session[AUTH_USER_KEY] = {"email": "user@example.com"}
    session[BUSINESS_NAME_INPUT_KEY] = "Demo Co"
    session[PROFILE_DRAFT_KEY] = {"business_name": "Demo Co"}
    session[PROFILE_RESEARCH_RESULT_KEY] = {"verification_summary": "Verified"}
    session[PROFILE_SAVE_URI_KEY] = "firestore://demo/id"
    session[POST_SAVE_REQUESTED_DATA_KEY] = ["customers"]
    session[POST_SAVE_REQUEST_NOTES_KEY] = "Only verified companies"
    session[LEAD_RESULTS_KEY] = {"export_name": "demo.xlsx"}
    session.save()

    clear_workspace_state(session)

    assert session[AUTH_USER_KEY] == {"email": "user@example.com"}
    assert BUSINESS_NAME_INPUT_KEY not in session
    assert PROFILE_DRAFT_KEY not in session
    assert PROFILE_RESEARCH_RESULT_KEY not in session
    assert PROFILE_SAVE_URI_KEY not in session
    assert POST_SAVE_REQUESTED_DATA_KEY not in session
    assert POST_SAVE_REQUEST_NOTES_KEY not in session
    assert LEAD_RESULTS_KEY not in session


def test_clear_workspace_state_can_clear_auth_too() -> None:
    session = localhost_client().session
    session[AUTH_USER_KEY] = {"email": "user@example.com"}
    session.save()

    clear_workspace_state(session, clear_auth=True)

    assert AUTH_USER_KEY not in session
