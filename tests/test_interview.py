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
        website="https://aarohanfoods.example",
        description="Healthy snack brand for retail and distributor channels.",
        industry="Food and beverage",
        location="Mumbai, India",
    )

    question = interviewer.next_question(draft, transcript=[])

    assert question is not None
    assert question.focus_fields == [
        "discovery_modes",
        "opportunity_type_needed",
        "goals",
    ]
    assert question.question.startswith("Reply in one block:")
    assert "```text" in question.question
    assert "Opportunity types:" in question.question


def test_opening_question_uses_compact_label_block() -> None:
    interviewer = IntakeInterviewer()

    question = interviewer.opening_question()

    assert question.question == (
        "Reply in one block:\n"
        "```text\n"
        "Name:\n"
        "Website:\n"
        "What you sell:\n"
        "Industry:\n"
        "Base location:\n"
        "```"
    )


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


def test_interviewer_treats_filters_and_constraints_as_optional() -> None:
    interviewer = IntakeInterviewer()
    draft = IntakeDraft(
        business_name="Aarohan Foods",
        website="https://aarohanfoods.example",
        description="Healthy snack brand for retail and distributor channels.",
        industry="Food and beverage",
        location="Mumbai, India",
        discovery_modes=["customers", "partners"],
        opportunity_type_needed="Retail and channel growth",
        goals=["Expand modern trade"],
        target_geographies=["India", "UAE"],
        ideal_customer_profile="Retail chains and distributors",
        preferred_company_sizes=["SMB", "Mid-market"],
        preferred_sectors=["Retail", "Distribution"],
        budget="Balanced",
        offerings=["Healthy snacks", "Private label packs"],
    )

    assert interviewer.missing_fields(draft) == []


def test_interviewer_collects_required_details_in_at_most_six_questions() -> None:
    interviewer = IntakeInterviewer()
    draft = IntakeDraft()
    transcript: list[dict[str, str]] = []
    questions_asked = 0
    question = interviewer.opening_question()

    answers = [
        (
            "Name: Aarohan Foods "
            "Website: aarohanfoods.example "
            "What you sell: Healthy snacks and private label snack packs "
            "Industry: Food and beverage "
            "Base location: Mumbai, India"
        ),
        (
            "Opportunity types: customers, partners "
            "Primary need: find retail buyers and channel partners "
            "Goals: expand modern trade, grow distributor reach"
        ),
        (
            "Target markets: India, UAE "
            "Ideal customer profile: regional grocery chains and distributors "
            "serving health-focused consumers"
        ),
        (
            "Preferred company sizes: SMB, Mid-market "
            "Preferred sectors: Retail, Distribution "
            "Offerings: millet snacks, private label packs"
        ),
        "Budget comfort: balanced",
    ]

    for answer in answers:
        questions_asked += 1
        transcript.append({"role": "assistant", "content": question.question})
        transcript.append({"role": "user", "content": answer})
        draft = interviewer.apply_answer(
            draft,
            answer,
            focus_fields=question.focus_fields,
            transcript=transcript,
        )
        next_question = interviewer.next_question(draft, transcript=transcript)
        if next_question is None:
            break
        question = next_question

    assert questions_asked <= 6
    assert interviewer.missing_fields(draft) == []
