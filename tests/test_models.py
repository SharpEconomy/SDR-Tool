from __future__ import annotations

from hackindia_leads.models import PUBLIC_LEAD_COLUMNS, EmailValidation, Lead


def test_email_validation_score_and_accepted() -> None:
    validation = EmailValidation(
        syntax_valid=True,
        mx_valid=True,
        smtp_code=250,
        smtp_message="ok",
    )

    assert validation.score == 3
    assert validation.accepted is True


def test_email_validation_rejects_failed_smtp_probe() -> None:
    validation = EmailValidation(
        syntax_valid=True,
        mx_valid=True,
        smtp_code=550,
        smtp_message="rejected",
    )

    assert validation.accepted is False


def test_lead_as_row_contains_expected_keys() -> None:
    lead = Lead(
        source="ethglobal",
        event_name="ETHGlobal Mumbai",
        event_url="https://ethglobal.com/events/mumbai",
        sponsor_company="ENS",
        sponsor_website="https://ens.domains",
        sponsor_domain="ens.domains",
        decision_maker_name="Jane Doe",
        decision_maker_title="Head of Partnerships",
        decision_maker_email="jane@ens.domains",
        contact_source="public-search-pattern",
        linkedin_url="https://linkedin.com/in/jane",
        email_smtp_code=250,
        email_score=3,
        email_accepted=True,
        evidence="embedded-json",
    )

    row = lead.as_row()

    assert row["sponsor_company"] == "ENS"
    assert row["decision_maker_email"] == "jane@ens.domains"
    assert row["email_accepted"] is True


def test_lead_as_export_row_excludes_internal_validation_fields() -> None:
    lead = Lead(
        source="ethglobal",
        event_name="ETHGlobal Mumbai",
        event_url="https://ethglobal.com/events/mumbai",
        sponsor_company="ENS",
        sponsor_website="https://ens.domains",
        sponsor_domain="ens.domains",
        decision_maker_name="Jane Doe",
        decision_maker_title="Head of Partnerships",
        decision_maker_email="jane@ens.domains",
        contact_source="public-search-pattern",
        linkedin_url="https://linkedin.com/in/jane",
        email_smtp_code=250,
        email_score=3,
        email_accepted=True,
        evidence="embedded-json",
    )

    row = lead.as_export_row()

    assert list(row) == PUBLIC_LEAD_COLUMNS
    assert "contact_source" not in row
    assert "email_smtp_code" not in row
    assert "email_score" not in row
    assert "email_accepted" not in row
