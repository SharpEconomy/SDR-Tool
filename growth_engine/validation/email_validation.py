from __future__ import annotations

import dns.resolver
from email_validator import EmailNotValidError, validate_email

from growth_engine.config import Settings
from growth_engine.models import ContactValidation


class EmailValidatorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(
        self,
        email: str,
        *,
        include_mx_lookup: bool = True,
    ) -> ContactValidation:
        try:
            result = validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            return ContactValidation(False, False)

        mx_valid = False
        if include_mx_lookup:
            mx_valid = bool(self._resolve_mx(result.domain))

        return ContactValidation(
            syntax_valid=True,
            mx_valid=mx_valid,
        )

    def _resolve_mx(self, domain: str) -> list[str]:
        try:
            answers = dns.resolver.resolve(domain, "MX")
            records = sorted(answers, key=lambda answer: answer.preference)
            return [str(record.exchange).rstrip(".") for record in records]
        except Exception:
            return []
