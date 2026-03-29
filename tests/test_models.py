from __future__ import annotations

import pytest

from hackindia_leads.models import PUBLIC_LEAD_COLUMNS, EmailValidation, Lead


def _build_lead(**overrides: object) -> Lead:
    lead_kwargs = {
        "source": "ethglobal",
        "event_name": "ETHGlobal Mumbai",
        "event_url": "https://ethglobal.com/events/mumbai",
        "sponsor_company": "ENS",
        "sponsor_website": "https://ens.domains",
        "sponsor_domain": "ens.domains",
        "company_segment": "Web3",
        "recently_funded": True,
        "recent_funding_signal": "Raised funding in 2025",
        "company_location": "New York, US",
        "location_priority": "US",
        "developer_adoption_need": True,
        "market_visibility_need": True,
        "decision_maker_name": "Jane Doe",
        "decision_maker_title": "Head of Partnerships",
        "decision_maker_email": "jane@ens.domains",
        "contact_source": "public-search-pattern",
        "linkedin_url": "https://linkedin.com/in/jane",
        "email_smtp_code": 250,
        "email_score": 3,
        "email_accepted": True,
        "evidence": "embedded-json",
        "qualification_notes": "Developer ecosystem push after recent funding.",
        "qualification_score": 91,
        "qualification_accepted": True,
        "contact_review_notes": "Strong partnerships owner.",
        "contact_review_score": 88,
        "contact_review_accepted": True,
    }
    lead_kwargs.update(overrides)
    return Lead(**lead_kwargs)


@pytest.mark.parametrize(
    ("smtp_code", "smtp_message", "expected_score", "expected_accepted"),
    [
        (250, "ok", 3, True),
        (550, "rejected", 2, False),
    ],
)
def test_email_validation_score_and_acceptance(
    smtp_code: int,
    smtp_message: str,
    expected_score: int,
    expected_accepted: bool,
) -> None:
    validation = EmailValidation(
        syntax_valid=True,
        mx_valid=True,
        smtp_code=smtp_code,
        smtp_message=smtp_message,
    )

    assert validation.score == expected_score
    assert validation.accepted is expected_accepted


def test_lead_as_row_contains_expected_keys() -> None:
    lead = _build_lead()

    row = lead.as_row()

    assert row["sponsor_company"] == "ENS"
    assert row["company_segment"] == "Web3"
    assert row["decision_maker_email"] == "jane@ens.domains"
    assert row["email_accepted"] is True
    assert row["contact_review_accepted"] is True


def test_lead_as_export_row_excludes_internal_validation_fields() -> None:
    lead = _build_lead()

    row = lead.as_export_row()
    internal_fields = set(lead.as_row()) - set(PUBLIC_LEAD_COLUMNS)

    assert list(row) == PUBLIC_LEAD_COLUMNS
    assert set(row).isdisjoint(internal_fields)
