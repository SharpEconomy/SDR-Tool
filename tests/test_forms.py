from __future__ import annotations

from growth_engine_web.forms import (
    PostSaveRequestForm,
    ProfileSectionForm,
    SourceResearchForm,
)


def test_source_research_form_normalizes_whitespace() -> None:
    form = SourceResearchForm(
        {
            "business_name": "  Demo   Co  ",
            "website": "  demo.example  ",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["business_name"] == "Demo Co"
    assert form.cleaned_data["website"] == "demo.example"


def test_profile_section_form_coerces_lists_and_urls() -> None:
    form = ProfileSectionForm(
        {
            "description": "  B2B analytics platform ",
            "user_urls": "demo.example\nhttps://demo.example/about",
            "offerings": "Analytics, Automation\nAnalytics",
        },
        field_names=("description", "user_urls", "offerings"),
    )

    assert form.is_valid()
    assert form.cleaned_partial_values() == {
        "description": "B2B analytics platform",
        "user_urls": ["https://demo.example", "https://demo.example/about"],
        "offerings": ["Analytics", "Automation"],
    }


def test_post_save_request_form_normalizes_modes_and_notes() -> None:
    form = PostSaveRequestForm(
        {
            "requested_data": ["customers", "partners"],
            "notes": "  Only   verified   companies  ",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["requested_data"] == ["customers", "partners"]
    assert form.cleaned_data["notes"] == "Only verified companies"


def test_post_save_request_form_rejects_invalid_modes() -> None:
    form = PostSaveRequestForm(
        {
            "requested_data": ["customers", "invalid_mode"],
            "notes": "Only verified companies",
        }
    )

    assert not form.is_valid()
    assert "requested_data" in form.errors
