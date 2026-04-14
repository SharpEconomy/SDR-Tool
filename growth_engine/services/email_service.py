from __future__ import annotations

from http import HTTPStatus

import requests

from growth_engine.config import Settings


class EmailDeliveryUnavailableError(RuntimeError):
    """Raised when SendGrid delivery cannot be completed."""


class EmailDeliveryService:
    SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(
            self.settings.sendgrid_api_key and self.settings.sendgrid_from_email
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
                "SendGrid delivery is not configured for this environment."
            )

        try:
            response = requests.post(
                self.SENDGRID_API_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": recipient}]}],
                    "from": self._sender_payload(),
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=self.settings.sendgrid_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise EmailDeliveryUnavailableError(
                f"SendGrid request failed: {exc}"
            ) from exc

        if response.status_code != HTTPStatus.ACCEPTED:
            raise EmailDeliveryUnavailableError(self._build_error_message(response))

    def _sender_payload(self) -> dict[str, str]:
        sender = {"email": self.settings.sendgrid_from_email}
        if self.settings.sendgrid_from_name:
            sender["name"] = self.settings.sendgrid_from_name
        return sender

    def _build_error_message(self, response: requests.Response) -> str:
        detail = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, list):
                messages = []
                for item in errors:
                    if not isinstance(item, dict):
                        continue
                    message = str(item.get("message", "")).strip()
                    field = str(item.get("field", "")).strip()
                    if message and field:
                        messages.append(f"{message} ({field})")
                    elif message:
                        messages.append(message)
                detail = "; ".join(messages)
        if not detail:
            detail = response.text.strip() or response.reason or "Unknown error"
        return f"SendGrid rejected the email ({response.status_code}): {detail}"
