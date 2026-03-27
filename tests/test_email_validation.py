from __future__ import annotations

from types import SimpleNamespace

from email_validator import EmailNotValidError

from hackindia_leads.models import EmailValidation
from hackindia_leads.services import email_validation as email_module
from hackindia_leads.services.email_validation import EmailValidatorService


def test_validate_rejects_invalid_syntax(settings, monkeypatch) -> None:
    service = EmailValidatorService(settings)

    def invalid(email, check_deliverability):
        raise EmailNotValidError("bad")

    monkeypatch.setattr(email_module, "validate_email", invalid)

    result = service.validate("bad-email")

    assert result == EmailValidation(False, False, None, None)


def test_validate_collects_mx_and_smtp(settings, monkeypatch) -> None:
    service = EmailValidatorService(settings)
    monkeypatch.setattr(
        email_module,
        "validate_email",
        lambda email, check_deliverability: SimpleNamespace(domain="example.com"),
    )
    monkeypatch.setattr(service, "_resolve_mx", lambda domain: ["mx.example.com"])
    monkeypatch.setattr(service, "_smtp_probe", lambda email, host: (250, "accepted"))

    result = service.validate("hello@example.com")

    assert result.syntax_valid is True
    assert result.mx_valid is True
    assert result.smtp_code == 250
    assert result.score == 3


def test_resolve_mx_returns_empty_on_error(settings, monkeypatch) -> None:
    service = EmailValidatorService(settings)

    def broken(domain, record_type):
        raise RuntimeError("dns fail")

    monkeypatch.setattr(email_module.dns.resolver, "resolve", broken)

    assert service._resolve_mx("example.com") == []
