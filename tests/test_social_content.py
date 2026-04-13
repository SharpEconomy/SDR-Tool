from __future__ import annotations

import pytest

from growth_engine.models import SocialContentRequest
from growth_engine.services import EmailDeliveryService, EmailDeliveryUnavailableError
from growth_engine.services.social_content import SocialContentService
from tests.helpers import build_intake_draft, build_research_result


def test_social_content_service_generates_fallback_package(settings) -> None:
    sent = {}

    class _SearchClient:
        def search(self, query, max_results=5):
            return []

    class _OpenAIService:
        def is_available(self):
            return False

    class _EmailService:
        def send_email(self, *, recipient, subject, body):
            sent["recipient"] = recipient
            sent["subject"] = subject
            sent["body"] = body

    service = SocialContentService(
        settings,
        search_client=_SearchClient(),
        openai_service=_OpenAIService(),
        email_service=_EmailService(),
    )

    result = service.generate(
        draft=build_intake_draft(),
        research_result=build_research_result(),
        request=SocialContentRequest(
            campaign_goal="Build awareness",
            channels=["linkedin", "twitter_x"],
            notes="Use practical proof points",
            delivery_email="user@example.com",
        ),
    )

    assert result.strategy.objective == "Build awareness"
    assert len(result.channel_content) == 2
    assert result.channel_content[0].channel == "linkedin"
    assert result.audit_record.workflow_type == "social_media_content"
    assert result.email_status == "sent"
    assert sent["recipient"] == "user@example.com"
    assert "Humans handle publishing" in sent["body"]


def test_social_content_service_marks_email_failure(settings) -> None:
    class _SearchClient:
        def search(self, query, max_results=5):
            return []

    class _OpenAIService:
        def is_available(self):
            return False

    class _EmailService:
        def send_email(self, *, recipient, subject, body):
            raise EmailDeliveryUnavailableError("smtp timeout")

    service = SocialContentService(
        settings,
        search_client=_SearchClient(),
        openai_service=_OpenAIService(),
        email_service=_EmailService(),
    )

    result = service.generate(
        draft=build_intake_draft(),
        research_result=build_research_result(),
        request=SocialContentRequest(
            campaign_goal="Build awareness",
            channels=["linkedin"],
            notes="Use practical proof points",
            delivery_email="user@example.com",
        ),
    )

    assert result.email_status == "failed"
    assert result.email_error == "smtp timeout"
    assert result.audit_record.metadata["email_delivery_status"] == "failed"


def test_email_delivery_service_requires_configuration(settings) -> None:
    service = EmailDeliveryService(settings)

    with pytest.raises(EmailDeliveryUnavailableError) as exc_info:
        service.send_email(
            recipient="user@example.com",
            subject="Demo",
            body="Hello",
        )

    assert "SMTP delivery is not configured" in str(exc_info.value)
