from __future__ import annotations

import importlib
import sys
import types

import pytest

from growth_engine.storage import FirestoreProfileStore
from growth_engine.storage.artifacts import _import_google_cloud_module


def test_firestore_profile_store_saves_payload(settings, monkeypatch) -> None:
    captured = {}

    class _Document:
        def __init__(self, document_id: str) -> None:
            self.document_id = document_id

        def set(self, payload):
            captured["document_id"] = self.document_id
            captured["payload"] = payload

    class _Collection:
        def document(self, document_id: str):
            return _Document(document_id)

    class _Client:
        def __init__(self, project=None, credentials=None, database=None):
            captured["project"] = project
            captured["database"] = database

        def collection(self, name: str):
            captured["collection"] = name
            return _Collection()

    firestore_module = types.ModuleType("google.cloud.firestore")
    firestore_module.Client = _Client
    cloud_module = types.ModuleType("google.cloud")
    cloud_module.firestore = firestore_module
    google_module = types.ModuleType("google")
    google_module.cloud = cloud_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", firestore_module)
    monkeypatch.setattr(
        "growth_engine.storage.artifacts.get_google_credentials",
        lambda settings: ("creds", "demo-project"),
    )

    store = FirestoreProfileStore(settings, settings.firestore_profile_collection)
    uri = store.save(
        "demo-profile", {"status": "confirmed", "profile": {"business_name": "Demo"}}
    )

    assert captured["collection"] == settings.firestore_profile_collection
    assert captured["document_id"] == "demo-profile"
    assert captured["payload"]["status"] == "confirmed"
    assert uri.endswith(f"/{settings.firestore_profile_collection}/demo-profile")


def test_import_google_cloud_module_raises_helpful_message(monkeypatch) -> None:
    original_import_module = importlib.import_module

    def _raise_missing(module_name: str):
        if module_name == "google.cloud.firestore":
            raise ModuleNotFoundError("No module named 'google.cloud'")
        return original_import_module(module_name)

    monkeypatch.setattr(importlib, "import_module", _raise_missing)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        _import_google_cloud_module("google.cloud.firestore", "google-cloud-firestore")

    assert "google-cloud-firestore" in str(exc_info.value)
    assert "python -m pip install -r requirements.txt" in str(exc_info.value)
