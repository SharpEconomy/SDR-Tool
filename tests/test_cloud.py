from __future__ import annotations

import base64
import json
import types
from dataclasses import asdict

from growth_engine.cloud.credentials import get_google_credentials
from growth_engine.cloud.functions import pubsub_decision_handler, run_decision_job
from growth_engine.cloud.pubsub import DEFAULT_PUBSUB_TOPIC, PubSubOrchestrator


def test_run_decision_job_returns_summary(settings, monkeypatch, intake) -> None:
    summary = {
        "business_name": intake.business_name,
        "opportunity_count": 1,
        "skipped_count": 0,
        "top_opportunities": [],
        "export_name": "demo.xlsx",
        "export_uri": "gs://bucket/demo.xlsx",
        "run_id": "run-1",
    }
    monkeypatch.setattr(
        "growth_engine.cloud.functions.DecisionEngine.run",
        lambda self, incoming: type(
            "Result",
            (),
            {
                "profile": type(
                    "Profile", (), {"business_name": intake.business_name}
                )(),
                "opportunities": [],
                "skipped_entities": [],
                "export_name": "demo.xlsx",
                "export_uri": "gs://bucket/demo.xlsx",
                "audit_record": type("Audit", (), {"run_id": "run-1"})(),
            },
        )(),
    )

    result = run_decision_job(asdict(intake), settings)

    assert result["business_name"] == summary["business_name"]
    assert result["export_uri"] == summary["export_uri"]


def test_pubsub_decision_handler_decodes_payload(settings, monkeypatch, intake) -> None:
    monkeypatch.setattr(
        "growth_engine.cloud.functions.run_decision_job",
        lambda payload: {
            "business_name": payload["business_name"],
            "opportunity_count": 0,
        },
    )
    event = {
        "data": base64.b64encode(json.dumps(asdict(intake)).encode("utf-8")).decode(
            "utf-8"
        )
    }

    result = pubsub_decision_handler(event)

    assert result["business_name"] == intake.business_name


def test_pubsub_orchestrator_publishes(settings, intake, monkeypatch) -> None:
    captured = {}

    class _Future:
        def result(self):
            return "message-1"

    class _Publisher:
        def __init__(self, credentials=None):
            captured["credentials"] = credentials

        def topic_path(self, project_id, topic):
            captured["topic_path"] = (project_id, topic)
            return f"projects/{project_id}/topics/{topic}"

        def publish(self, topic_path, payload):
            captured["published"] = (topic_path, payload)
            return _Future()

    import sys

    pubsub_module = types.ModuleType("google.cloud.pubsub_v1")
    pubsub_module.PublisherClient = _Publisher
    google_module = types.ModuleType("google")
    cloud_module = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", pubsub_module)

    message_id = PubSubOrchestrator(settings).publish_intake(intake)

    assert message_id == "message-1"
    assert captured["topic_path"] == (
        settings.google_cloud_project,
        DEFAULT_PUBSUB_TOPIC,
    )


def test_google_credentials_support_base64_service_account(
    settings, monkeypatch
) -> None:
    settings.google_cloud_service_account_json_b64 = base64.b64encode(
        json.dumps(
            {"project_id": "encoded-project", "client_email": "svc@test"}
        ).encode("utf-8")
    ).decode("utf-8")

    captured = {}

    class _CredentialsFactory:
        @staticmethod
        def from_service_account_info(info, scopes=None):
            captured["info"] = info
            captured["scopes"] = scopes
            return "creds"

    import sys

    google_module = types.ModuleType("google")
    oauth2_module = types.ModuleType("google.oauth2")
    service_account_module = types.ModuleType("google.oauth2.service_account")
    service_account_module.Credentials = _CredentialsFactory
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_module)
    monkeypatch.setitem(
        sys.modules,
        "google.oauth2.service_account",
        service_account_module,
    )

    credentials, project_id = get_google_credentials(settings, scopes=["scope-1"])

    assert credentials == "creds"
    assert project_id == "encoded-project"
    assert captured["info"]["client_email"] == "svc@test"
    assert captured["scopes"] == ["scope-1"]
