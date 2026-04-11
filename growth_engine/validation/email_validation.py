from __future__ import annotations

import smtplib

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
        include_smtp_probe: bool | None = None,
    ) -> ContactValidation:
        if include_smtp_probe is None:
            include_smtp_probe = self.settings.smtp_probe_enabled

        try:
            result = validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            return ContactValidation(False, False, None, None)

        mx_valid = False
        mx_hosts: list[str] = []
        if include_mx_lookup:
            mx_hosts = self._resolve_mx(result.domain)
            mx_valid = bool(mx_hosts)

        smtp_code: int | None = None
        smtp_message: str | None = None
        if include_smtp_probe and mx_hosts:
            smtp_code, smtp_message = self._smtp_probe(email, mx_hosts[0])

        return ContactValidation(
            syntax_valid=True,
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
                mx_host,
                25,
                timeout=self.settings.smtp_timeout_seconds,
            ) as server:
                server.ehlo_or_helo_if_needed()
                # Use the RFC 5321 null reverse-path for validation probes.
                server.mail("")
                code, message = server.rcpt(email)
                decoded = (
                    message.decode("utf-8", errors="ignore")
                    if isinstance(message, bytes)
                    else str(message)
                )
                return code, decoded
        except Exception as exc:
            return None, str(exc)
