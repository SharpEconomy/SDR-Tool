from __future__ import annotations

import smtplib

import dns.resolver
from email_validator import EmailNotValidError, validate_email

from hackindia_leads.config import Settings
from hackindia_leads.models import EmailValidation


class EmailValidatorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(
        self,
        email: str,
        *,
        include_mx_lookup: bool = True,
        include_smtp_probe: bool = True,
    ) -> EmailValidation:
        syntax_valid = False
        mx_valid = False
        smtp_code: int | None = None
        smtp_message: str | None = None

        try:
            result = validate_email(email, check_deliverability=False)
            syntax_valid = True
            domain = result.domain
        except EmailNotValidError:
            return EmailValidation(False, False, None, None)

        mx_hosts: list[str] = []
        if include_mx_lookup:
            mx_hosts = self._resolve_mx(domain)
            mx_valid = bool(mx_hosts)

        if include_smtp_probe and mx_hosts and self.settings.smtp_from_email:
            smtp_code, smtp_message = self._smtp_probe(email, mx_hosts[0])

        return EmailValidation(
            syntax_valid=syntax_valid,
            mx_valid=mx_valid,
            smtp_code=smtp_code,
            smtp_message=smtp_message,
        )

    def _resolve_mx(self, domain: str) -> list[str]:
        try:
            answers = dns.resolver.resolve(domain, "MX")
            records = sorted(answers, key=lambda answer: answer.preference)
            return [str(record.exchange).rstrip(".") for record in records]
        except Exception:
            return []

    def _smtp_probe(self, email: str, mx_host: str) -> tuple[int | None, str | None]:
        try:
            with smtplib.SMTP(
                mx_host, 25, timeout=self.settings.smtp_timeout_seconds
            ) as server:
                server.ehlo_or_helo_if_needed()
                server.mail(self.settings.smtp_from_email)
                code, message = server.rcpt(email)
                decoded = (
                    message.decode("utf-8", errors="ignore")
                    if isinstance(message, bytes)
                    else str(message)
                )
                return code, decoded
        except Exception as exc:
            return None, str(exc)
