from __future__ import annotations

from growth_engine.intake import IntakeInterviewer
from growth_engine.models import IntakeDraft


class _FakeInterviewModel:
    def is_available(self) -> bool:
        return True

    def extract_intake_update(self, payload):
        return {
            "industry": "Food and beverage",
            "location": "Mumbai, India",
        }

    def generate_intake_question(self, payload):
        return {
            "question": "Which website should I use as the main public reference?",
            "focus_fields": ["website"],
            "rationale": "website_missing",
        }


def test_interviewer_uses_model_to_fill_missing_business_fields() -> None:
    interviewer = IntakeInterviewer(_FakeInterviewModel())
    draft = IntakeDraft()

    updated = interviewer.apply_answer(
        draft,
        "Aarohan Foods is a healthy snack brand.",
        focus_fields=["business_name", "description", "industry", "location"],
        transcript=[],
    )

    assert updated.business_name == "Aarohan Foods"
    assert updated.description == "Aarohan Foods is a healthy snack brand."
    assert updated.industry == "Food and beverage"
    assert updated.location == "Mumbai, India"


def test_interviewer_next_question_skips_answered_fields() -> None:
    interviewer = IntakeInterviewer()
    draft = IntakeDraft(
        business_name="Aarohan Foods",
        description="Healthy snack brand for retail and distributor channels.",
        industry="Food and beverage",
        location="Mumbai, India",
    )

    question = interviewer.next_question(draft, transcript=[])

    assert question is not None
    assert question.focus_fields == ["website"]
    assert "website" in question.question.lower()


def test_interviewer_replaces_list_fields_on_refinement() -> None:
    interviewer = IntakeInterviewer()
    draft = IntakeDraft(preferred_sectors=["Retail"])

    updated = interviewer.apply_answer(
        draft,
        "FMCG, Distribution",
        focus_fields=["preferred_sectors"],
        transcript=[],
    )

    assert updated.preferred_sectors == ["FMCG", "Distribution"]


def test_interviewer_uses_model_generated_question_when_available() -> None:
    interviewer = IntakeInterviewer(_FakeInterviewModel())
    draft = IntakeDraft(
        business_name="Aarohan Foods",
        description="Healthy snack brand for retail and distributor channels.",
        industry="Food and beverage",
        location="Mumbai, India",
    )

    question = interviewer.next_question(draft, transcript=[])

    assert question is not None
    assert question.focus_fields == ["website"]
    assert question.rationale == "website_missing"
