from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any

from growth_engine.models import IntakeDraft, ProfileResearchResult, ResearchSource

AUTH_USER_KEY = "growth_engine_auth_user"
BUSINESS_NAME_INPUT_KEY = "growth_engine_business_name_input"
WEBSITE_INPUT_KEY = "growth_engine_website_input"
PROFILE_DRAFT_KEY = "growth_engine_profile_draft"
PROFILE_RESEARCH_RESULT_KEY = "growth_engine_profile_research_result"
PROFILE_SAVE_URI_KEY = "growth_engine_profile_save_uri"
POST_SAVE_REQUESTED_DATA_KEY = "growth_engine_post_save_requested_data"
POST_SAVE_REQUEST_NOTES_KEY = "growth_engine_post_save_request_notes"
LEAD_RESULTS_KEY = "growth_engine_lead_results"


def _serialize_source(source: ResearchSource) -> dict[str, str]:
    return asdict(source)


def _deserialize_source(payload: dict[str, Any]) -> ResearchSource:
    return ResearchSource(
        kind=str(payload.get("kind", "")),
        url=str(payload.get("url", "")),
        title=str(payload.get("title", "")),
        snippet=str(payload.get("snippet", "")),
    )


def serialize_draft(draft: IntakeDraft) -> dict[str, Any]:
    return asdict(draft)


def deserialize_draft(payload: dict[str, Any] | None) -> IntakeDraft | None:
    if not payload:
        return None
    return IntakeDraft(**payload)


def serialize_research_result(result: ProfileResearchResult) -> dict[str, Any]:
    return {
        "draft": serialize_draft(result.draft),
        "sources": [_serialize_source(source) for source in result.sources],
        "verification_summary": result.verification_summary,
    }


def deserialize_research_result(
    payload: dict[str, Any] | None,
) -> ProfileResearchResult | None:
    if not payload:
        return None
    draft = deserialize_draft(payload.get("draft"))
    if draft is None:
        return None
    return ProfileResearchResult(
        draft=draft,
        sources=[_deserialize_source(item) for item in payload.get("sources", [])],
        verification_summary=str(payload.get("verification_summary", "")),
    )


def get_auth_user(session) -> dict[str, Any] | None:
    user = session.get(AUTH_USER_KEY)
    return user if isinstance(user, dict) else None


def set_auth_user(session, user: dict[str, Any]) -> None:
    session[AUTH_USER_KEY] = user
    session.modified = True


def clear_workspace_state(session, *, clear_auth: bool = False) -> None:
    keys = [
        BUSINESS_NAME_INPUT_KEY,
        WEBSITE_INPUT_KEY,
        PROFILE_DRAFT_KEY,
        PROFILE_RESEARCH_RESULT_KEY,
        PROFILE_SAVE_URI_KEY,
        POST_SAVE_REQUESTED_DATA_KEY,
        POST_SAVE_REQUEST_NOTES_KEY,
        LEAD_RESULTS_KEY,
    ]
    if clear_auth:
        keys.append(AUTH_USER_KEY)
    for key in keys:
        session.pop(key, None)
    session.modified = True


def get_draft(session) -> IntakeDraft | None:
    return deserialize_draft(session.get(PROFILE_DRAFT_KEY))


def set_draft(session, draft: IntakeDraft | None) -> None:
    if draft is None:
        session.pop(PROFILE_DRAFT_KEY, None)
    else:
        session[PROFILE_DRAFT_KEY] = serialize_draft(draft)
    session.modified = True


def get_research_result(session) -> ProfileResearchResult | None:
    return deserialize_research_result(session.get(PROFILE_RESEARCH_RESULT_KEY))


def set_research_result(session, result: ProfileResearchResult | None) -> None:
    if result is None:
        session.pop(PROFILE_RESEARCH_RESULT_KEY, None)
    else:
        session[PROFILE_RESEARCH_RESULT_KEY] = serialize_research_result(result)
    session.modified = True


def get_post_save_request(session) -> dict[str, Any]:
    return {
        "requested_data": list(session.get(POST_SAVE_REQUESTED_DATA_KEY, []) or []),
        "notes": str(session.get(POST_SAVE_REQUEST_NOTES_KEY, "") or ""),
    }


def set_post_save_request(
    session,
    *,
    requested_data: list[str],
    notes: str,
) -> None:
    session[POST_SAVE_REQUESTED_DATA_KEY] = requested_data
    session[POST_SAVE_REQUEST_NOTES_KEY] = notes
    session.modified = True


def clear_lead_results(session) -> None:
    session.pop(LEAD_RESULTS_KEY, None)
    session.modified = True


def get_lead_results(session) -> dict[str, Any] | None:
    payload = session.get(LEAD_RESULTS_KEY)
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("opportunity_rows"), list):
        return None
    if not isinstance(payload.get("skipped_rows"), list):
        return None
    if not isinstance(payload.get("export_name"), str):
        return None
    if not isinstance(payload.get("export_payload_b64"), str):
        return None
    return payload


def get_lead_export_bytes(session) -> bytes | None:
    payload = get_lead_results(session)
    if payload is None:
        return None
    try:
        return base64.b64decode(payload["export_payload_b64"].encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def set_lead_results(
    session,
    *,
    opportunity_rows: list[dict[str, object]],
    skipped_rows: list[dict[str, object]],
    export_name: str,
    export_bytes: bytes,
) -> None:
    session[LEAD_RESULTS_KEY] = {
        "opportunity_rows": opportunity_rows,
        "skipped_rows": skipped_rows,
        "export_name": export_name,
        "export_payload_b64": base64.b64encode(export_bytes).decode("ascii"),
    }
    session.modified = True
