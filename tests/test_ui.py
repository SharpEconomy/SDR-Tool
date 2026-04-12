from __future__ import annotations

import re

import streamlit as st

from growth_engine.models import IntakeDraft
from growth_engine.ui import app as ui


def test_parse_list_input_dedupes_items() -> None:
    parsed = ui._parse_list_input("retail, distribution\nretail")

    assert parsed == ["retail", "distribution"]


def test_parse_multiline_urls_normalizes_scheme() -> None:
    parsed = ui._parse_multiline_urls("demo.example\nhttps://demo.example")

    assert parsed == ["https://demo.example"]


def test_normalize_auth_event_accepts_authenticated_payload() -> None:
    normalized = ui._normalize_auth_event(
        {
            "status": "authenticated",
            "email": "user@example.com",
            "token": "token-123",
            "uid": "uid-123",
            "displayName": "Example User",
        }
    )

    assert normalized == {
        "status": "authenticated",
        "user": {
            "email": "user@example.com",
            "token": "token-123",
            "uid": "uid-123",
            "displayName": "Example User",
        },
    }


def test_reset_workspace_state_clears_profile_state() -> None:
    st.session_state.clear()
    ui._ensure_session_state()
    st.session_state[ui.BUSINESS_NAME_INPUT_KEY] = "Demo"
    st.session_state[ui.WEBSITE_INPUT_KEY] = "demo.example"
    st.session_state[ui.PROFILE_DRAFT_KEY] = IntakeDraft(business_name="Demo")
    st.session_state[ui.PROFILE_SAVE_URI_KEY] = "firestore://demo"
    st.session_state[ui.POST_SAVE_REQUESTED_DATA_KEY] = ["customers"]
    st.session_state[ui.POST_SAVE_REQUEST_NOTES_KEY] = "Only verified companies"

    ui._reset_workspace_state()

    assert st.session_state[ui.BUSINESS_NAME_INPUT_KEY] == ""
    assert st.session_state[ui.WEBSITE_INPUT_KEY] == ""
    assert st.session_state[ui.PROFILE_DRAFT_KEY] is None
    assert st.session_state[ui.PROFILE_SAVE_URI_KEY] is None
    assert st.session_state[ui.POST_SAVE_REQUESTED_DATA_KEY] == []
    assert st.session_state[ui.POST_SAVE_REQUEST_NOTES_KEY] == ""


def test_draft_from_form_values_parses_lists_and_urls() -> None:
    draft = ui._draft_from_form_values(
        {
            "business_name": "Demo Co",
            "website": "https://demo.example",
            "description": "B2B analytics platform",
            "industry": "Software",
            "location": "Mumbai, India",
            "target_geographies": "India, UAE",
            "budget": "Balanced",
            "ideal_customer_profile": "SMB and mid-market teams",
            "preferred_company_sizes": "SMB, Mid-market",
            "preferred_sectors": "Retail, Logistics",
            "offerings": "Analytics, Automation",
            "goals": "Grow pipeline, Expand channels",
            "discovery_modes": "customers, partners",
            "opportunity_type_needed": "Qualified buyers",
            "inclusion_keywords": "data, analytics",
            "exclusion_keywords": "jobs, careers",
            "vendor_constraints": "None",
            "supplier_constraints": "None",
            "user_urls": "demo.example\nhttps://about.demo.example",
        }
    )

    assert draft.target_geographies == ["India", "UAE"]
    assert draft.discovery_modes == ["customers", "partners"]
    assert draft.user_urls == ["https://demo.example", "https://about.demo.example"]


def test_build_research_document_id_uses_slug_and_timestamp() -> None:
    document_id = ui._build_research_document_id("Demo Company")

    assert re.fullmatch(r"demo-company-\d{14}", document_id)


def test_normalize_error_message_uses_fallback_for_blank_exception() -> None:
    message = ui._normalize_error_message(
        Exception(),
        fallback="Profile could not be saved. Please try again.",
    )

    assert message == "Profile could not be saved. Please try again."


def test_format_discovery_mode_label_humanizes_underscored_value() -> None:
    assert ui._format_discovery_mode_label("service_providers") == "Service Providers"


def test_human_friendly_profile_html_contains_plain_language_sections() -> None:
    draft = IntakeDraft(
        business_name="Demo Co",
        website="https://demo.example",
        description="B2B analytics platform",
        industry="Software",
        location="Mumbai, India",
        target_geographies=["India", "UAE"],
        ideal_customer_profile="Operations teams",
        preferred_company_sizes=["SMB"],
        preferred_sectors=["Retail"],
        offerings=["Analytics"],
        goals=["Grow pipeline"],
        discovery_modes=["customers"],
        opportunity_type_needed="Qualified buyers",
    )

    rendered = ui._human_friendly_profile_html(draft)

    assert "Business snapshot" in rendered
    assert "Best-fit market" in rendered
    assert "Commercial setup" in rendered
    assert "B2B analytics platform" in rendered
    assert "summary-chip" in rendered
    assert "summary-line-full" in rendered
    assert "India, UAE" not in rendered


def test_human_friendly_profile_html_wraps_trusted_urls_inside_card() -> None:
    draft = IntakeDraft(
        business_name="Demo Co",
        website="https://demo.example",
        description="B2B analytics platform",
        industry="Software",
        location="Mumbai, India",
        offerings=["Analytics"],
        goals=["Grow pipeline"],
        discovery_modes=["customers"],
        user_urls=[
            "https://demo.example/really/long/path/that/should/stay/inside/the/card",
        ],
    )

    rendered = ui._human_friendly_profile_html(draft)

    assert "Trusted URLs" in rendered
    assert "summary-chip-wrap" in rendered
    assert "href=" not in rendered


def test_update_draft_from_partial_values_updates_only_one_card() -> None:
    original = IntakeDraft(
        business_name="Demo Co",
        website="https://demo.example",
        description="Old description",
        industry="Software",
        location="Mumbai, India",
        goals=["Grow pipeline"],
    )

    updated = ui._update_draft_from_partial_values(
        original,
        {
            "description": "New description",
            "industry": "AI software",
        },
    )

    assert updated.description == "New description"
    assert updated.industry == "AI software"
    assert updated.website == "https://demo.example"
    assert updated.goals == ["Grow pipeline"]


def test_serialize_list_field_returns_human_readable_text() -> None:
    comma_separated = ui._serialize_list_field(["India", "UAE", "India"])
    newline_separated = ui._serialize_list_field(
        ["https://demo.example", "https://about.demo.example"]
    )

    assert comma_separated == "India, UAE"
    assert newline_separated == "https://demo.example\nhttps://about.demo.example"


def test_human_friendly_profile_hides_none_and_not_specified_fields() -> None:
    draft = IntakeDraft(
        business_name="Demo Co",
        website="https://demo.example",
        description="B2B analytics platform",
        industry="Software",
        location="Mumbai, India",
        offerings=["Analytics"],
        goals=["Grow pipeline"],
        discovery_modes=["customers"],
        opportunity_type_needed="Not specified",
        vendor_constraints="None",
        supplier_constraints="None",
    )

    rendered = ui._human_friendly_profile_html(draft)

    assert "Primary need" not in rendered
    assert "Vendor constraints" not in rendered
    assert "Supplier constraints" not in rendered
    assert "summary-empty" not in rendered
