from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from growth_engine.models import SocialContentRequest
from growth_engine.services import EmailDeliveryService, EmailDeliveryUnavailableError
from growth_engine.services import email_service as email_module
from growth_engine.services.social_content import SocialContentService
from tests.helpers import build_intake_draft, build_research_result


class _SearchClient:
    def search(self, query, max_results=5):
        return []


class _OpenAIService:
    def is_available(self):
        return False


def _build_social_service(settings, *, email_service) -> SocialContentService:
    return SocialContentService(
        settings,
        search_client=_SearchClient(),
        openai_service=_OpenAIService(),
        email_service=email_service,
    )


def _build_request(*, channels: list[str]) -> SocialContentRequest:
    return SocialContentRequest(
        campaign_goal="Build awareness",
        channels=channels,
        notes="Use practical proof points",
        delivery_email="user@example.com",
    )


def _configure_sendgrid(settings) -> EmailDeliveryService:
    settings.sendgrid_api_key = "sg-key"
    settings.sendgrid_from_email = "noreply@example.com"
    settings.sendgrid_from_name = "Growth Engine"
    return EmailDeliveryService(settings)


def test_social_content_service_generates_fallback_package(settings) -> None:
    sent = {}

    class _EmailService:
        def send_email(self, *, recipient, subject, body):
            sent["recipient"] = recipient
            sent["subject"] = subject
            sent["body"] = body

    service = _build_social_service(settings, email_service=_EmailService())

    result = service.generate(
        draft=build_intake_draft(),
        research_result=build_research_result(),
        request=_build_request(channels=["linkedin", "twitter_x"]),
    )

    assert result.strategy.objective == "Build awareness"
    assert len(result.channel_content) == 2
    assert result.channel_content[0].channel == "linkedin"
    assert result.audit_record.workflow_type == "social_media_content"
    assert result.email_status == "sent"
    assert sent["recipient"] == "user@example.com"
    assert "Humans handle publishing" in sent["body"]


def test_social_content_service_marks_email_failure(settings) -> None:
    class _EmailService:
        def send_email(self, *, recipient, subject, body):
            raise EmailDeliveryUnavailableError("SendGrid request failed: timed out")

    service = _build_social_service(settings, email_service=_EmailService())

    result = service.generate(
        draft=build_intake_draft(),
        research_result=build_research_result(),
        request=_build_request(channels=["linkedin"]),
    )

    assert result.email_status == "failed"
    assert result.email_error == "SendGrid request failed: timed out"
    assert result.audit_record.metadata["email_delivery_status"] == "failed"


def test_email_delivery_service_requires_configuration(settings) -> None:
    service = EmailDeliveryService(settings)

    with pytest.raises(EmailDeliveryUnavailableError) as exc_info:
        service.send_email(
            recipient="user@example.com",
            subject="Demo",
            body="Hello",
        )

    assert "SendGrid delivery is not configured" in str(exc_info.value)


def test_email_delivery_service_sends_via_sendgrid(settings, monkeypatch) -> None:
    service = _configure_sendgrid(settings)
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(status_code=202, text="", reason="Accepted")

    monkeypatch.setattr(email_module.requests, "post", fake_post)

    service.send_email(
        recipient="user@example.com",
        subject="Demo",
        body="Hello",
    )

    assert captured["url"] == service.SENDGRID_API_URL
    assert captured["headers"]["Authorization"] == "Bearer sg-key"
    assert captured["timeout"] == 5
    assert captured["json"]["from"] == {
        "email": "noreply@example.com",
        "name": "Growth Engine",
    }
    assert captured["json"]["personalizations"] == [
        {"to": [{"email": "user@example.com"}]}
    ]
    assert captured["json"]["content"] == [{"type": "text/plain", "value": "Hello"}]


def test_email_delivery_service_surfaces_sendgrid_error(settings, monkeypatch) -> None:
    service = _configure_sendgrid(settings)

    class _FailureResponse:
        status_code = 400
        text = ""
        reason = "Bad Request"

        def json(self):
            return {
                "errors": [
                    {
                        "message": "The from address does not match a verified Sender Identity."
                    }
                ]
            }

    monkeypatch.setattr(
        email_module.requests,
        "post",
        lambda *args, **kwargs: _FailureResponse(),
    )

    with pytest.raises(EmailDeliveryUnavailableError) as exc_info:
        service.send_email(
            recipient="user@example.com",
            subject="Demo",
            body="Hello",
        )

    assert "SendGrid rejected the email (400)" in str(exc_info.value)
    assert "verified Sender Identity" in str(exc_info.value)


def test_email_delivery_service_surfaces_network_errors(settings, monkeypatch) -> None:
    service = _configure_sendgrid(settings)

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(email_module.requests, "post", raise_timeout)

    with pytest.raises(EmailDeliveryUnavailableError) as exc_info:
        service.send_email(
            recipient="user@example.com",
            subject="Demo",
            body="Hello",
        )

    assert "SendGrid request failed: timed out" in str(exc_info.value)
