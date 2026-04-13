from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict

from growth_engine.cloud.credentials import get_google_credentials
from growth_engine.config import Settings
from growth_engine.models import AuditRecord


def _import_google_cloud_module(module_name: str, package_name: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = exc.name or ""
        if missing_name.startswith("google.cloud") or (
            not missing_name and module_name.startswith("google.cloud")
        ):
            raise ModuleNotFoundError(
                f"Missing dependency '{package_name}'. "
                "Install the project dependencies with "
                "`python -m pip install -r requirements.txt`."
            ) from exc
        raise


class AuditStore(ABC):
    @abstractmethod
    def save(self, record: AuditRecord) -> str | None:
        raise NotImplementedError


class ProfileStore(ABC):
    @abstractmethod
    def save(self, document_id: str, payload: dict[str, object]) -> str | None:
        raise NotImplementedError


class NoOpAuditStore(AuditStore):
    def save(self, record: AuditRecord) -> str | None:
        return None


class NoOpProfileStore(ProfileStore):
    def save(self, document_id: str, payload: dict[str, object]) -> str | None:
        return None


class FirestoreAuditStore(AuditStore):
    def __init__(self, settings: Settings, collection_name: str) -> None:
        self.settings = settings
        self.collection_name = collection_name

    def save(self, record: AuditRecord) -> str:
        firestore = _import_google_cloud_module(
            "google.cloud.firestore",
            "google-cloud-firestore",
        )

        credentials, project_id = get_google_credentials(self.settings)
        client = firestore.Client(
            project=project_id or None,
            credentials=credentials,
            database=self.settings.firestore_database,
        )
        payload = json.loads(json.dumps(asdict(record), default=str))
        client.collection(self.collection_name).document(record.run_id).set(payload)
        return (
            "firestore://"
            f"{project_id or 'default'}/{self.settings.firestore_database}/"
            f"{self.collection_name}/{record.run_id}"
        )


class FirestoreProfileStore(ProfileStore):
    def __init__(self, settings: Settings, collection_name: str) -> None:
        self.settings = settings
        self.collection_name = collection_name

    def save(self, document_id: str, payload: dict[str, object]) -> str:
        firestore = _import_google_cloud_module(
            "google.cloud.firestore",
            "google-cloud-firestore",
        )

        credentials, project_id = get_google_credentials(self.settings)
        client = firestore.Client(
            project=project_id or None,
            credentials=credentials,
            database=self.settings.firestore_database,
        )
        safe_payload = json.loads(json.dumps(payload, default=str))
        client.collection(self.collection_name).document(document_id).set(safe_payload)
        return (
            "firestore://"
            f"{project_id or 'default'}/{self.settings.firestore_database}/"
            f"{self.collection_name}/{document_id}"
        )
