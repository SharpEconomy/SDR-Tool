from __future__ import annotations

import re

from growth_engine import profile_flow
from growth_engine.models import IntakeDraft


def test_parse_list_input_dedupes_items() -> None:
    parsed = profile_flow.parse_list_input("retail, distribution\nretail")

    assert parsed == ["retail", "distribution"]


def test_parse_multiline_urls_normalizes_scheme() -> None:
    parsed = profile_flow.parse_multiline_urls("demo.example\nhttps://demo.example")

    assert parsed == ["https://demo.example"]


def test_build_research_document_id_uses_slug_and_timestamp() -> None:
    document_id = profile_flow.build_research_document_id("Demo Company")

    assert re.fullmatch(r"demo-company-\d{14}", document_id)


def test_normalize_error_message_uses_fallback_for_blank_exception() -> None:
    message = profile_flow.normalize_error_message(
        Exception(),
        fallback="Profile could not be saved. Please try again.",
    )

    assert message == "Profile could not be saved. Please try again."


def test_format_discovery_mode_label_humanizes_underscored_value() -> None:
    assert (
        profile_flow.format_discovery_mode_label("service_providers")
        == "Service Providers"
    )


def test_build_summary_cards_contains_plain_language_sections() -> None:
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

    cards = profile_flow.build_summary_cards(draft)

    assert [card["title"] for card in cards] == [
        "Business snapshot",
        "Best-fit market",
        "Commercial setup",
    ]
    assert cards[0]["rows"][0]["kind"] == "paragraph"
    assert cards[1]["rows"][0]["kind"] == "chips"


def test_build_summary_cards_wraps_trusted_urls_inside_card() -> None:
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

    cards = profile_flow.build_summary_cards(draft)
    commercial_card = next(card for card in cards if card["id"] == "commercial_setup")
    trusted_urls = next(
        row for row in commercial_card["rows"] if row["field_name"] == "user_urls"
    )

    assert trusted_urls["kind"] == "chips"
    assert trusted_urls["wrap"] is True


def test_update_draft_from_partial_values_updates_only_one_card() -> None:
    original = IntakeDraft(
        business_name="Demo Co",
        website="https://demo.example",
        description="Old description",
        industry="Software",
        location="Mumbai, India",
        goals=["Grow pipeline"],
    )

    updated = profile_flow.update_draft_from_partial_values(
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
    comma_separated = profile_flow.serialize_list_field(["India", "UAE", "India"])
    newline_separated = profile_flow.serialize_list_field(
        ["https://demo.example", "https://about.demo.example"]
    )

    assert comma_separated == "India, UAE"
    assert newline_separated == "https://demo.example\nhttps://about.demo.example"


def test_build_summary_cards_hides_none_and_not_specified_fields() -> None:
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

    cards = profile_flow.build_summary_cards(draft)
    labels = [row["label"] for card in cards for row in card["rows"]]

    assert "Primary need" not in labels
    assert "Vendor constraints" not in labels
    assert "Supplier constraints" not in labels
