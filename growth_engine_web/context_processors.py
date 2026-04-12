from __future__ import annotations

from growth_engine_web.runtime import get_runtime_settings


def app_shell(request):
    settings = get_runtime_settings()
    auth_enabled = bool(
        settings.firebase_api_key
        and settings.firebase_auth_domain
        and settings.firebase_project_id
    )
    return {
        "app_name": settings.app_name,
        "firebase_auth_enabled": auth_enabled,
        "firebase_client_config": {
            "apiKey": settings.firebase_api_key,
            "authDomain": settings.firebase_auth_domain,
            "projectId": settings.firebase_project_id,
        },
    }
