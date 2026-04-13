from __future__ import annotations

from growth_engine_web.runtime import get_runtime_settings


def app_shell(request):
    settings = get_runtime_settings()
    return {
        "app_name": settings.app_name,
    }
