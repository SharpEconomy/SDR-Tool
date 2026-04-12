from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("", include("growth_engine_web.urls")),
]
