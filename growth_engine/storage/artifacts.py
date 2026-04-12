from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict

from growth_engine.cloud.credentials import get_google_credentials
from growth_engine.config import Settings
from growth_engine.models import AuditRecord

DEFAULT_EXPORT_PREFIX = "growth-engine-exports"


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


class ArtifactStore(ABC):
    @abstractmethod
    def save_bytes(self, name: str, payload: bytes) -> str | None:
        raise NotImplementedError


class AuditStore(ABC):
    @abstractmethod
    def save(self, record: AuditRecord) -> str | None:
        raise NotImplementedError


class ProfileStore(ABC):
    @abstractmethod
    def save(self, document_id: str, payload: dict[str, object]) -> str | None:
        raise NotImplementedError


class NoOpArtifactStore(ArtifactStore):
    def save_bytes(self, name: str, payload: bytes) -> str | None:
        return None


class NoOpAuditStore(AuditStore):
    def save(self, record: AuditRecord) -> str | None:
        return None


class NoOpProfileStore(ProfileStore):
    def save(self, document_id: str, payload: dict[str, object]) -> str | None:
        return None


class FirebaseStorageArtifactStore(ArtifactStore):
    def __init__(
        self,
        settings: Settings,
        bucket_name: str,
        *,
        export_prefix: str = DEFAULT_EXPORT_PREFIX,
    ) -> None:
        self.settings = settings
        self.bucket_name = bucket_name
        self.export_prefix = export_prefix.strip("/ ")

    def save_bytes(self, name: str, payload: bytes) -> str:
        storage = _import_google_cloud_module(
            "google.cloud.storage",
            "google-cloud-storage",
        )

        credentials, project_id = get_google_credentials(self.settings)
        client = storage.Client(project=project_id or None, credentials=credentials)
        bucket = client.bucket(self.bucket_name)
        blob_name = f"{self.export_prefix}/{name}" if self.export_prefix else name
        blob = bucket.blob(blob_name)
        blob.upload_from_string(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return f"gs://{self.bucket_name}/{blob_name}"


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
