from __future__ import annotations

import html
from dataclasses import asdict
from datetime import UTC, datetime

import streamlit as st

from growth_engine.auth import firebase_login_screen
from growth_engine.config import Settings
from growth_engine.models import DISCOVERY_MODES, IntakeDraft, ProfileResearchResult
from growth_engine.profile_research import BusinessProfileResearcher
from growth_engine.storage import FirestoreProfileStore
from growth_engine.utils import dedupe_keep_order, normalize_whitespace, slugify

AUTH_USER_KEY = "growth_engine_auth_user"
AUTH_LOGOUT_VERSION_KEY = "growth_engine_auth_logout_version"
AUTH_LOGOUT_PENDING_KEY = "growth_engine_auth_logout_pending"
BUSINESS_NAME_INPUT_KEY = "growth_engine_business_name_input"
WEBSITE_INPUT_KEY = "growth_engine_website_input"
PROFILE_DRAFT_KEY = "growth_engine_profile_draft"
PROFILE_RESEARCH_RESULT_KEY = "growth_engine_profile_research_result"
PROFILE_SAVE_URI_KEY = "growth_engine_profile_save_uri"
PROFILE_SAVE_ERROR_KEY = "growth_engine_profile_save_error"
PROFILE_RESEARCH_ERROR_KEY = "growth_engine_profile_research_error"
ACTIVE_EDIT_CARD_KEY = "growth_engine_active_edit_card"
POST_SAVE_REQUESTED_DATA_KEY = "growth_engine_post_save_requested_data"
POST_SAVE_REQUEST_NOTES_KEY = "growth_engine_post_save_request_notes"

LIST_FIELDS = {
    "target_geographies",
    "preferred_company_sizes",
    "preferred_sectors",
    "offerings",
    "goals",
    "discovery_modes",
    "inclusion_keywords",
    "exclusion_keywords",
    "user_urls",
}
WRAPPED_LIST_FIELDS = {"user_urls"}
MULTILINE_FIELDS = {"description", "ideal_customer_profile"}
FIELD_LABELS = {
    "business_name": "Business name",
    "website": "Website",
    "description": "What you sell",
    "industry": "Industry",
    "location": "Base location",
    "target_geographies": "Target markets",
    "budget": "Budget comfort",
    "ideal_customer_profile": "Ideal customer profile",
    "preferred_company_sizes": "Preferred company sizes",
    "preferred_sectors": "Preferred sectors",
    "offerings": "Offerings",
    "goals": "Goals",
    "discovery_modes": "Opportunity types",
    "opportunity_type_needed": "Primary need",
    "inclusion_keywords": "Must-have keywords",
    "exclusion_keywords": "Avoid keywords",
    "vendor_constraints": "Vendor constraints",
    "supplier_constraints": "Supplier constraints",
    "user_urls": "Trusted URLs",
}
FIELD_HELP_TEXT = {
    "business_name": "The company name that should be saved.",
    "website": "Primary public website for this business.",
    "description": "Plain-language summary of what the business sells.",
    "industry": "Best-fit business category.",
    "location": "Primary business base or headquarters.",
    "target_geographies": "Comma-separated markets this business should focus on.",
    "budget": "Budget posture inferred from the public profile. Edit if you know better.",
    "ideal_customer_profile": "Who this business should most likely target.",
    "preferred_company_sizes": "Comma-separated company size targets.",
    "preferred_sectors": "Comma-separated sectors to prioritize.",
    "offerings": "Comma-separated products or services.",
    "goals": "Comma-separated business outcomes or priorities.",
    "discovery_modes": "Comma-separated opportunity types such as customers or partners.",
    "opportunity_type_needed": "The main type of opportunity the business wants next.",
    "inclusion_keywords": "Comma-separated must-match terms.",
    "exclusion_keywords": "Comma-separated terms to avoid.",
    "vendor_constraints": "Rules or limits for vendors.",
    "supplier_constraints": "Rules or limits for suppliers.",
    "user_urls": "One trusted URL per line.",
}
FIELD_ORDER = (
    "business_name",
    "website",
    "description",
    "industry",
    "location",
    "target_geographies",
    "budget",
    "ideal_customer_profile",
    "preferred_company_sizes",
    "preferred_sectors",
    "offerings",
    "goals",
    "discovery_modes",
    "opportunity_type_needed",
    "inclusion_keywords",
    "exclusion_keywords",
    "vendor_constraints",
    "supplier_constraints",
    "user_urls",
)
SUMMARY_CARD_CONFIGS = (
    {
        "id": "business_snapshot",
        "title": "Business snapshot",
        "subtitle": "What this company appears to be",
        "fields": ("description", "industry", "location", "website"),
    },
    {
        "id": "best_fit_market",
        "title": "Best-fit market",
        "subtitle": "Who this business should likely go after",
        "fields": (
            "target_geographies",
            "ideal_customer_profile",
            "preferred_company_sizes",
            "preferred_sectors",
        ),
    },
    {
        "id": "commercial_setup",
        "title": "Commercial setup",
        "subtitle": "What the engine will use downstream",
        "fields": (
            "offerings",
            "goals",
            "discovery_modes",
            "opportunity_type_needed",
            "inclusion_keywords",
            "exclusion_keywords",
            "vendor_constraints",
            "supplier_constraints",
            "user_urls",
        ),
    },
)


def render() -> None:
    st.set_page_config(page_title="Growth Decision Engine", layout="wide")
    _inject_styles()
    settings = Settings.load()
    _ensure_session_state()

    if settings.firebase_api_key and not _render_auth_gate(settings):
        return

    hero_col, source_col = st.columns([1.15, 0.95], gap="large")
    with hero_col:
        _render_hero()
    with source_col:
        _render_source_intake(settings)

    research_result = st.session_state[PROFILE_RESEARCH_RESULT_KEY]
    if research_result is None:
        _render_empty_state()
        return

    research_error = _normalize_error_message(
        st.session_state[PROFILE_RESEARCH_ERROR_KEY],
        fallback="Profile research could not be completed. Please try again.",
    )
    if research_error:
        st.error(research_error)

    _render_confirmation_flow(settings, research_result)

    save_error = _normalize_error_message(
        st.session_state[PROFILE_SAVE_ERROR_KEY],
        fallback="Profile could not be saved. Please try again.",
    )
    if save_error:
        st.error(save_error)

    save_uri = st.session_state[PROFILE_SAVE_URI_KEY]
    if save_uri:
        st.success("Profile confirmed and saved to Firestore.")
        st.caption(f"Saved record: `{save_uri}`")
        _render_post_save_data_request()


def _render_auth_gate(settings: Settings) -> bool:
    current_user = st.session_state[AUTH_USER_KEY]
    logout_pending = st.session_state[AUTH_LOGOUT_PENDING_KEY]
    auth_result = firebase_login_screen(
        {
            "apiKey": settings.firebase_api_key,
            "authDomain": settings.firebase_auth_domain,
            "projectId": settings.firebase_project_id,
        },
        show_login_button=current_user is None and not logout_pending,
        logout_version=st.session_state[AUTH_LOGOUT_VERSION_KEY],
        key="growth_engine_firebase_auth",
    )
    auth_event = _normalize_auth_event(auth_result)

    if auth_event is not None:
        if auth_event["status"] == "authenticated" and not logout_pending:
            if current_user != auth_event["user"]:
                st.session_state[AUTH_USER_KEY] = auth_event["user"]
                st.rerun()
        elif auth_event["status"] == "signed_out":
            if current_user is not None or logout_pending:
                st.session_state[AUTH_USER_KEY] = None
                st.session_state[AUTH_LOGOUT_PENDING_KEY] = False
                st.rerun()
        elif auth_event["status"] == "error":
            st.error(
                auth_event["message"]
                or "Authentication failed. Please try signing in again."
            )

    if st.session_state[AUTH_LOGOUT_PENDING_KEY]:
        st.info("Signing out...")
        return False

    current_user = st.session_state[AUTH_USER_KEY]
    if current_user:
        email_col, logout_col = st.columns([6, 1])
        email_col.caption(f"Signed in as {current_user.get('email', 'User')}")
        if logout_col.button("Log out", use_container_width=True):
            _reset_workspace_state()
            st.session_state[AUTH_USER_KEY] = None
            st.session_state[AUTH_LOGOUT_PENDING_KEY] = True
            st.session_state[AUTH_LOGOUT_VERSION_KEY] += 1
            st.rerun()
        return True

    st.markdown(
        "<div class='step-card'><h3>Sign in</h3><p>Use Google sign-in to protect saved business profiles.</p></div>",
        unsafe_allow_html=True,
    )
    return False


def _render_hero() -> None:
    st.markdown(
        """
        <section class="hero-shell">
          <div class="hero-kicker">AI business foundation capture</div>
          <h1>Start with a name and website.</h1>
          <p>
            The app researches the company, cross-checks the public evidence,
            drafts the full business profile, and asks you to confirm before saving.
          </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_source_intake(settings: Settings) -> None:
    st.markdown(
        """
        <div class="step-card source-card-shell">
          <div class="step-label">Step 1</div>
          <h3>Business source</h3>
          <p>Enter the business name and primary website. The app will gather the rest.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("growth_engine_source_form", clear_on_submit=False):
        left, right = st.columns(2)
        with left:
            st.text_input(
                "Business name",
                key=BUSINESS_NAME_INPUT_KEY,
                placeholder="Aarohan Foods",
            )
        with right:
            st.text_input(
                "Website",
                key=WEBSITE_INPUT_KEY,
                placeholder="aarohanfoods.example",
            )
        submitted = st.form_submit_button(
            "Research from web",
            use_container_width=True,
        )

    if submitted:
        _research_profile(settings)


def _research_profile(settings: Settings) -> None:
    business_name = normalize_whitespace(st.session_state[BUSINESS_NAME_INPUT_KEY])
    website = normalize_whitespace(st.session_state[WEBSITE_INPUT_KEY])
    st.session_state[PROFILE_RESEARCH_ERROR_KEY] = None
    st.session_state[PROFILE_SAVE_ERROR_KEY] = None
    st.session_state[PROFILE_SAVE_URI_KEY] = None

    if not business_name or not website:
        st.session_state[PROFILE_RESEARCH_ERROR_KEY] = (
            "Enter both the business name and website before starting research."
        )
        return

    researcher = BusinessProfileResearcher(settings)
    try:
        with st.spinner(
            "Researching the website, search results, and model verification..."
        ):
            result = researcher.research(
                business_name=business_name,
                website=website,
            )
    except Exception as exc:
        st.session_state[PROFILE_RESEARCH_ERROR_KEY] = str(exc)
        return

    st.session_state[PROFILE_RESEARCH_RESULT_KEY] = result
    st.session_state[PROFILE_DRAFT_KEY] = result.draft


def _render_confirmation_flow(
    settings: Settings,
    research_result: ProfileResearchResult,
) -> None:
    draft: IntakeDraft = st.session_state[PROFILE_DRAFT_KEY]
    left, right = st.columns([1.3, 0.9], gap="large")

    with left:
        st.markdown(
            """
            <div class="step-card">
              <div class="step-label">Step 2</div>
              <h3>Review the business profile</h3>
              <p>
                Start with the three summary cards. If something looks wrong,
                click the edit icon on that card, update that section, then
                confirm the full profile.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_summary_cards(draft)
        _render_active_edit_card(draft)
        confirm_left, confirm_right = st.columns([1.35, 1], gap="large")
        confirm_left.markdown(
            """
            <div class="edit-guide confirm-guide">
              <strong>Ready to save?</strong> Confirm only after each card reads naturally and reflects the business correctly.
            </div>
            """,
            unsafe_allow_html=True,
        )
        if confirm_right.button(
            "Confirm this profile and save",
            use_container_width=True,
            key="confirm_profile_button",
        ):
            _save_confirmed_profile(settings, research_result)
            st.rerun()

    with right:
        st.markdown(
            """
            <div class="step-card">
              <div class="step-label">Step 3</div>
              <h3>Verification</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='verification-shell'>{html.escape(research_result.verification_summary)}</div>",
            unsafe_allow_html=True,
        )
        for source in research_result.sources[:6]:
            st.markdown(
                f"""
                <article class="source-card">
                  <div class="source-kind">{html.escape(source.kind)}</div>
                  <h4>{html.escape(source.title)}</h4>
                  <p>{html.escape(source.snippet[:280])}</p>
                  <a href="{html.escape(source.url)}" target="_blank">{html.escape(source.url)}</a>
                </article>
                """,
                unsafe_allow_html=True,
            )


def _render_summary_cards(draft: IntakeDraft) -> None:
    for card_config in SUMMARY_CARD_CONFIGS:
        card_col, action_col = st.columns([10, 2], gap="small")
        card_col.markdown(
            _summary_card(
                card_config["title"],
                card_config["subtitle"],
                _summary_card_rows(card_config["fields"], draft),
            ),
            unsafe_allow_html=True,
        )
        is_active = st.session_state[ACTIVE_EDIT_CARD_KEY] == card_config["id"]
        if action_col.button(
            "Edit",
            key=f"edit_card_{card_config['id']}",
            help=f"Edit {card_config['title']}",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state[ACTIVE_EDIT_CARD_KEY] = (
                None if is_active else card_config["id"]
            )
            st.rerun()


def _render_active_edit_card(draft: IntakeDraft) -> None:
    card_id = st.session_state[ACTIVE_EDIT_CARD_KEY]
    if not card_id:
        return

    card_config = next(
        (config for config in SUMMARY_CARD_CONFIGS if config["id"] == card_id),
        None,
    )
    if card_config is None:
        st.session_state[ACTIVE_EDIT_CARD_KEY] = None
        return

    _render_edit_card_dialog(draft, card_id, card_config)


@st.dialog("Edit profile section", width="large")
def _render_edit_card_dialog(
    draft: IntakeDraft,
    card_id: str,
    card_config: dict[str, object],
) -> None:
    st.caption(
        f"{card_config['title']}: {card_config['subtitle']}. "
        "Update this section only, then save changes."
    )
    with st.form(f"edit_card_form_{card_id}", clear_on_submit=False):
        values: dict[str, object] = {}
        left, right = st.columns(2, gap="large")
        columns = [left, right]
        for index, field_name in enumerate(card_config["fields"]):
            with columns[index % 2]:
                values[field_name] = _draft_field_input(
                    field_name,
                    getattr(draft, field_name),
                    key_prefix=f"card_edit_{card_id}",
                )
        save_col, cancel_col = st.columns(2, gap="large")
        saved = save_col.form_submit_button(
            "Save section changes",
            use_container_width=True,
        )
        cancelled = cancel_col.form_submit_button(
            "Close without saving",
            use_container_width=True,
        )
    if saved:
        st.session_state[PROFILE_DRAFT_KEY] = _update_draft_from_partial_values(
            draft, values
        )
        st.session_state[ACTIVE_EDIT_CARD_KEY] = None
        st.rerun()
    if cancelled:
        st.session_state[ACTIVE_EDIT_CARD_KEY] = None
        st.rerun()


def _human_friendly_profile_html(draft: IntakeDraft) -> str:
    cards = [
        _summary_card(
            config["title"],
            config["subtitle"],
            _summary_card_rows(config["fields"], draft),
        )
        for config in SUMMARY_CARD_CONFIGS
    ]
    return f"<div class='profile-overview'>{''.join(cards)}</div>"


def _summary_card(title: str, subtitle: str, lines: list[str]) -> str:
    detail_lines = "".join(
        (
            f"<div class='summary-line summary-line-full'>{line}</div>"
            if "summary-rich-text" in line
            else f"<div class='summary-line'>{line}</div>"
        )
        for line in lines
        if normalize_whitespace(line)
    )
    return (
        "<article class='summary-card'>"
        f"<div class='summary-kicker'>{html.escape(subtitle)}</div>"
        f"<h4>{html.escape(title)}</h4>"
        f"{detail_lines}"
        "</article>"
    )


def _summary_card_rows(fields: tuple[str, ...], draft: IntakeDraft) -> list[str]:
    rows: list[str] = []
    for field_name in fields:
        value = getattr(draft, field_name)
        if _should_hide_summary_field(value):
            continue
        if field_name == "description":
            rows.append(_friendly_paragraph(value))
            continue
        rows.append(_friendly_pair(FIELD_LABELS[field_name], value, field_name))
    return rows


def _friendly_value(value: object, fallback: str = "Not confirmed") -> str:
    cleaned = normalize_whitespace(str(value or ""))
    return cleaned or fallback


def _friendly_pair(label: str, value: object, field_name: str | None = None) -> str:
    if isinstance(value, list):
        rendered = _friendly_token_group(
            value,
            wrap_items=field_name in WRAPPED_LIST_FIELDS,
        )
        return f"<span>{html.escape(label)}</span><div>{rendered}</div>"
    cleaned = _friendly_value(value, "Not confirmed")
    return f"<span>{html.escape(label)}</span><strong>{html.escape(cleaned)}</strong>"


def _friendly_paragraph(value: object) -> str:
    cleaned = _friendly_value(value, "Description not confirmed yet.")
    return f"<div class='summary-rich-text'>{html.escape(cleaned)}</div>"


def _friendly_token_group(value: list[str], *, wrap_items: bool = False) -> str:
    cleaned = dedupe_keep_order(value)
    if not cleaned:
        return ""
    chip_class = "summary-chip summary-chip-wrap" if wrap_items else "summary-chip"
    return "".join(
        f"<span class='{chip_class}'>{html.escape(item)}</span>" for item in cleaned
    )


def _should_hide_summary_field(value: object) -> bool:
    if isinstance(value, list):
        return len(dedupe_keep_order(value)) == 0
    cleaned = normalize_whitespace(str(value or "")).lower()
    return cleaned in {"", "none", "not specified", "not confirmed"}


def _draft_field_input(
    field_name: str,
    value: object,
    *,
    key_prefix: str = "profile_field",
) -> object:
    label = FIELD_LABELS[field_name]
    key = f"{key_prefix}_{field_name}"
    help_text = FIELD_HELP_TEXT[field_name]
    if field_name in LIST_FIELDS:
        seeded = _serialize_list_field(value)
        if field_name == "user_urls":
            return st.text_area(
                label, value=seeded, key=key, height=110, help=help_text
            )
        return st.text_area(label, value=seeded, key=key, height=90, help=help_text)
    if field_name in MULTILINE_FIELDS:
        return st.text_area(
            label,
            value=normalize_whitespace(str(value or "")),
            key=key,
            height=110,
            help=help_text,
        )
    return st.text_input(
        label,
        value=normalize_whitespace(str(value or "")),
        key=key,
        help=help_text,
    )


def _update_draft_from_partial_values(
    draft: IntakeDraft,
    values: dict[str, object],
) -> IntakeDraft:
    updated = IntakeDraft(**asdict(draft))
    for field_name, raw_value in values.items():
        setattr(updated, field_name, _coerce_field_value(field_name, raw_value))
    return updated


def _coerce_field_value(field_name: str, raw_value: object) -> object:
    if field_name in LIST_FIELDS:
        if field_name == "user_urls":
            return _parse_multiline_urls(str(raw_value or ""))
        return _parse_list_input(str(raw_value or ""))
    return normalize_whitespace(str(raw_value or ""))


def _draft_from_form_values(values: dict[str, object]) -> IntakeDraft:
    return IntakeDraft(
        business_name=normalize_whitespace(str(values["business_name"] or "")),
        website=normalize_whitespace(str(values["website"] or "")),
        description=normalize_whitespace(str(values["description"] or "")),
        industry=normalize_whitespace(str(values["industry"] or "")),
        location=normalize_whitespace(str(values["location"] or "")),
        target_geographies=_parse_list_input(str(values["target_geographies"] or "")),
        budget=normalize_whitespace(str(values["budget"] or "")),
        ideal_customer_profile=normalize_whitespace(
            str(values["ideal_customer_profile"] or "")
        ),
        preferred_company_sizes=_parse_list_input(
            str(values["preferred_company_sizes"] or "")
        ),
        preferred_sectors=_parse_list_input(str(values["preferred_sectors"] or "")),
        offerings=_parse_list_input(str(values["offerings"] or "")),
        goals=_parse_list_input(str(values["goals"] or "")),
        discovery_modes=_parse_list_input(str(values["discovery_modes"] or "")),
        opportunity_type_needed=normalize_whitespace(
            str(values["opportunity_type_needed"] or "")
        ),
        inclusion_keywords=_parse_list_input(str(values["inclusion_keywords"] or "")),
        exclusion_keywords=_parse_list_input(str(values["exclusion_keywords"] or "")),
        vendor_constraints=normalize_whitespace(
            str(values["vendor_constraints"] or "")
        ),
        supplier_constraints=normalize_whitespace(
            str(values["supplier_constraints"] or "")
        ),
        user_urls=_parse_multiline_urls(str(values["user_urls"] or "")),
    )


def _save_confirmed_profile(
    settings: Settings,
    research_result: ProfileResearchResult,
) -> None:
    draft: IntakeDraft = st.session_state[PROFILE_DRAFT_KEY]
    user = st.session_state[AUTH_USER_KEY] or {}
    document_id = _build_research_document_id(draft.business_name or "profile")
    payload = {
        "status": "confirmed",
        "confirmed_at": datetime.now(UTC).isoformat(),
        "confirmed_by": user.get("email", ""),
        "profile": asdict(draft),
        "verification_summary": research_result.verification_summary,
        "sources": [asdict(source) for source in research_result.sources],
    }
    st.session_state[PROFILE_SAVE_ERROR_KEY] = None
    try:
        store = FirestoreProfileStore(settings, settings.firestore_profile_collection)
        save_uri = store.save(document_id, payload)
    except Exception as exc:
        st.session_state[PROFILE_SAVE_URI_KEY] = None
        st.session_state[PROFILE_SAVE_ERROR_KEY] = _normalize_error_message(
            exc,
            fallback="Profile could not be saved. Check the Firestore configuration and try again.",
        )
        return
    st.session_state[PROFILE_SAVE_ERROR_KEY] = None
    st.session_state[PROFILE_SAVE_URI_KEY] = save_uri


def _build_research_document_id(business_name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{slugify(business_name) or 'business-profile'}-{stamp}"


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-shell">
          <h3>What happens next</h3>
          <p>
            The app fetches the public website, runs custom search, asks GPT-5.4 mini
            to cross-check the evidence, and then gives you an editable profile to approve.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _normalize_auth_event(auth_result: object) -> dict[str, object] | None:
    if not isinstance(auth_result, dict):
        return None

    status = str(auth_result.get("status") or "").strip().lower()
    if status == "signed_out":
        return {"status": "signed_out"}
    if status == "error":
        return {
            "status": "error",
            "message": str(auth_result.get("message") or "").strip(),
        }

    token = str(auth_result.get("token") or "").strip()
    email = str(auth_result.get("email") or "").strip()
    if not token or not email:
        return None

    return {
        "status": "authenticated",
        "user": {
            "email": email,
            "token": token,
            "uid": str(auth_result.get("uid") or "").strip(),
            "displayName": str(auth_result.get("displayName") or "").strip(),
        },
    }


def _normalize_error_message(raw_value: object, *, fallback: str) -> str | None:
    if raw_value is None:
        return None
    cleaned = normalize_whitespace(str(raw_value))
    return cleaned or fallback


def _render_post_save_data_request() -> None:
    st.markdown(
        """
        <div class="step-card">
          <div class="step-label">Next Step</div>
          <h3>What data do you want next?</h3>
          <p>Select the type of data you want the engine to find from this saved profile.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_modes = st.multiselect(
        "Choose one or more data types",
        options=DISCOVERY_MODES,
        default=st.session_state[POST_SAVE_REQUESTED_DATA_KEY],
        key=POST_SAVE_REQUESTED_DATA_KEY,
        format_func=_format_discovery_mode_label,
        placeholder="Select data types",
    )
    st.text_area(
        "Anything specific you want in that data?",
        key=POST_SAVE_REQUEST_NOTES_KEY,
        height=90,
        placeholder="Example: only India-based distributors with verified websites.",
    )
    if selected_modes:
        readable_modes = ", ".join(
            _format_discovery_mode_label(mode) for mode in selected_modes
        )
        st.info(f"Requested next data: {readable_modes}")


def _format_discovery_mode_label(mode: str) -> str:
    return mode.replace("_", " ").title()


def _ensure_session_state() -> None:
    defaults = {
        AUTH_USER_KEY: None,
        AUTH_LOGOUT_VERSION_KEY: 0,
        AUTH_LOGOUT_PENDING_KEY: False,
        BUSINESS_NAME_INPUT_KEY: "",
        WEBSITE_INPUT_KEY: "",
        PROFILE_DRAFT_KEY: None,
        PROFILE_RESEARCH_RESULT_KEY: None,
        PROFILE_SAVE_URI_KEY: None,
        PROFILE_SAVE_ERROR_KEY: None,
        PROFILE_RESEARCH_ERROR_KEY: None,
        ACTIVE_EDIT_CARD_KEY: None,
        POST_SAVE_REQUESTED_DATA_KEY: [],
        POST_SAVE_REQUEST_NOTES_KEY: "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_workspace_state() -> None:
    st.session_state[BUSINESS_NAME_INPUT_KEY] = ""
    st.session_state[WEBSITE_INPUT_KEY] = ""
    st.session_state[PROFILE_DRAFT_KEY] = None
    st.session_state[PROFILE_RESEARCH_RESULT_KEY] = None
    st.session_state[PROFILE_SAVE_URI_KEY] = None
    st.session_state[PROFILE_SAVE_ERROR_KEY] = None
    st.session_state[PROFILE_RESEARCH_ERROR_KEY] = None
    st.session_state[ACTIVE_EDIT_CARD_KEY] = None
    st.session_state[POST_SAVE_REQUESTED_DATA_KEY] = []
    st.session_state[POST_SAVE_REQUEST_NOTES_KEY] = ""


def _serialize_list_field(value: object) -> str:
    if isinstance(value, list):
        cleaned = dedupe_keep_order(
            [str(item) for item in value if normalize_whitespace(str(item))]
        )
        separator = "\n" if any("://" in str(item) for item in value) else ", "
        return separator.join(cleaned)
    return normalize_whitespace(str(value or ""))


def _parse_list_input(raw_value: str) -> list[str]:
    return dedupe_keep_order(
        [
            item
            for item in raw_value.replace("\n", ",").split(",")
            if normalize_whitespace(item)
        ]
    )


def _parse_multiline_urls(raw_value: str) -> list[str]:
    items = [normalize_whitespace(line) for line in raw_value.splitlines()]
    cleaned = []
    for item in items:
        if not item:
            continue
        cleaned.append(item if "://" in item else f"https://{item}")
    return dedupe_keep_order(cleaned)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap');

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(218, 231, 212, 0.72), transparent 28%),
                radial-gradient(circle at right 20%, rgba(236, 220, 196, 0.68), transparent 24%),
                linear-gradient(180deg, #f6f0e3 0%, #fbf8f1 100%);
            color: #19352a;
        }

        .hero-shell, .step-card, .empty-shell, .verification-shell, .source-card, .summary-card {
            background: rgba(255, 252, 246, 0.88);
            border: 1px solid rgba(35, 69, 53, 0.12);
            border-radius: 24px;
            box-shadow: 0 18px 40px rgba(36, 52, 41, 0.08);
        }

        .hero-shell {
            padding: 2rem 2.2rem;
            margin-bottom: 1.2rem;
        }

        .step-card, .verification-shell, .source-card, .empty-shell, .summary-card {
            padding: 1.05rem 1.2rem;
            margin-bottom: 0.9rem;
        }

        .hero-shell h1, .step-card h3, .source-card h4, .empty-shell h3, .summary-card h4 {
            font-family: "Fraunces", serif;
            margin: 0;
            color: #19352a;
        }

        .hero-shell p, .step-card p, .empty-shell p, .verification-shell, .source-card p, .source-card a {
            font-family: "Manrope", sans-serif;
            color: #496152;
        }

        .hero-kicker, .step-label, .source-kind {
            font-family: "Manrope", sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.72rem;
            color: #7a8f7f;
        }

        .verification-shell {
            color: #244032;
            line-height: 1.6;
            font-size: 0.95rem;
        }

        .profile-overview {
            display: grid;
            gap: 0.8rem;
            margin: 0.35rem 0 1rem;
        }

        .source-card-shell,
        .edit-card-shell {
            height: 100%;
        }

        .summary-kicker {
            font-family: "Manrope", sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #718474;
            font-size: 0.7rem;
            margin-bottom: 0.45rem;
        }

        .summary-line {
            display: grid;
            grid-template-columns: 138px 1fr;
            gap: 0.75rem;
            padding: 0.38rem 0;
            border-bottom: 1px solid rgba(35, 69, 53, 0.08);
            font-family: "Manrope", sans-serif;
        }

        .summary-line:last-child {
            border-bottom: 0;
        }

        .summary-line-full {
            display: block;
        }

        .summary-line > div {
            min-width: 0;
        }

        .summary-line > div:last-child {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            align-items: flex-start;
        }

        .summary-line span {
            color: #738476;
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .summary-line strong {
            color: #213f31;
            font-size: 0.95rem;
            line-height: 1.45;
            font-weight: 600;
        }

        .summary-rich-text {
            font-family: "Manrope", sans-serif;
            color: #213f31;
            line-height: 1.68;
            text-align: justify;
            padding: 0.15rem 0 0.2rem;
        }

        .summary-chip {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: #edf3eb;
            color: #294736;
            border-radius: 999px;
            padding: 0.28rem 0.72rem;
            border: 1px solid rgba(41, 71, 54, 0.1);
            font-family: "Manrope", sans-serif;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: default;
            user-select: none;
            max-width: 100%;
        }

        .summary-chip-wrap {
            white-space: normal;
            word-break: break-word;
            overflow-wrap: anywhere;
            text-align: left;
            justify-content: flex-start;
        }

        .summary-empty {
            font-family: "Manrope", sans-serif;
            color: #6c8173;
        }

        .edit-guide {
            font-family: "Manrope", sans-serif;
            color: #264636;
            background: rgba(228, 237, 229, 0.8);
            border: 1px solid rgba(44, 86, 65, 0.12);
            border-radius: 18px;
            padding: 0.9rem 1rem;
            margin: 0 0 1rem;
            line-height: 1.5;
        }

        .confirm-guide {
            margin-top: 0.1rem;
            margin-bottom: 0;
        }

        .source-card a {
            word-break: break-all;
        }

        .stButton > button,
        .stFormSubmitButton > button {
            background: linear-gradient(180deg, #204936 0%, #2d6b50 100%);
            color: #f9f5eb;
            border: 0;
        }

        button[kind="secondary"] {
            background: linear-gradient(180deg, #d7e3d5 0%, #bfd1bf 100%);
            color: #214333;
            border: 1px solid rgba(33, 67, 51, 0.12);
            box-shadow: none;
        }

        button[kind="secondary"]:hover,
        button[kind="secondary"]:focus {
            background: linear-gradient(180deg, #c9d9c7 0%, #b0c5b1 100%);
            color: #173526;
        }

        .stTextInput label, .stTextArea label {
            font-family: "Manrope", sans-serif;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
