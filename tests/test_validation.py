from __future__ import annotations

from types import SimpleNamespace

from email_validator import EmailNotValidError

from growth_engine.models import ContactValidation
from growth_engine.validation import email_validation as email_module
from growth_engine.validation.email_validation import EmailValidatorService


def test_validate_rejects_invalid_syntax(settings, monkeypatch) -> None:
    service = EmailValidatorService(settings)

    def invalid(email, check_deliverability):
        raise EmailNotValidError("bad")

    monkeypatch.setattr(email_module, "validate_email", invalid)

    result = service.validate("bad-email")

    assert result == ContactValidation(False, False)


def test_validate_skips_mx_lookup_when_requested(settings, monkeypatch) -> None:
    service = EmailValidatorService(settings)
    monkeypatch.setattr(
        email_module,
        "validate_email",
        lambda email, check_deliverability: SimpleNamespace(domain="example.com"),
    )
    monkeypatch.setattr(
        service,
        "_resolve_mx",
        lambda domain: (_ for _ in ()).throw(RuntimeError("should not run")),
    )

    result = service.validate(
        "hello@example.com",
        include_mx_lookup=False,
    )

    assert result.syntax_valid is True
    assert result.mx_valid is False
