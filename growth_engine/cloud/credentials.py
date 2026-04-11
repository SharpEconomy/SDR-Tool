from __future__ import annotations

import base64
import importlib
import json
from typing import Any

from growth_engine.config import Settings


def load_service_account_info(settings: Settings) -> dict[str, Any] | None:
    raw_b64 = settings.google_cloud_service_account_json_b64
    if raw_b64:
        decoded = base64.b64decode(raw_b64).decode("utf-8")
        return json.loads(decoded)
    return None


def get_google_credentials(
    settings: Settings,
    *,
    scopes: list[str] | None = None,
) -> tuple[object | None, str]:
    service_account_info = load_service_account_info(settings)
    project_id = settings.google_cloud_project

    if service_account_info:
        service_account = importlib.import_module("google.oauth2.service_account")
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
        )
        return credentials, service_account_info.get("project_id", project_id) or ""

    return None, project_id
