from __future__ import annotations

import smtplib
from email.message import EmailMessage

from growth_engine.config import Settings


class EmailDeliveryUnavailableError(RuntimeError):
    """Raised when SMTP delivery cannot be completed."""


class EmailDeliveryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_port
            and self.settings.smtp_from_email
        )

    def send_email(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        if not self.is_configured():
            raise EmailDeliveryUnavailableError(
                "SMTP delivery is not configured for this environment."
            )

        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        try:
            if self.settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                ) as client:
                    self._login(client)
                    client.send_message(message)
                return

            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as client:
                client.ehlo()
                if self.settings.smtp_use_tls:
                    client.starttls()
                    client.ehlo()
                self._login(client)
                client.send_message(message)
        except OSError as exc:
            raise EmailDeliveryUnavailableError(str(exc)) from exc
        except smtplib.SMTPException as exc:
            raise EmailDeliveryUnavailableError(str(exc)) from exc

    def _login(self, client: smtplib.SMTP) -> None:
        if not self.settings.smtp_username and not self.settings.smtp_password:
            return
        client.login(self.settings.smtp_username, self.settings.smtp_password)
