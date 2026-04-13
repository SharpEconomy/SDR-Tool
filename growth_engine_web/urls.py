from __future__ import annotations

from django.urls import path

from growth_engine_web import views

app_name = "growth_engine_web"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/analytics/", views.analytics_dashboard, name="analytics"),
    path("research/", views.research_profile, name="research"),
    path("edit/<str:card_id>/", views.edit_section, name="edit_section"),
    path("save/", views.save_profile, name="save_profile"),
    path("request-data/", views.request_data, name="request_data"),
    path(
        "social-content/",
        views.generate_social_content,
        name="generate_social_content",
    ),
    path("leads/download/", views.download_leads_export, name="download_leads_export"),
    path("auth/google/", views.google_login, name="google_login"),
    path("auth/google/callback/", views.google_callback, name="google_callback"),
    path("auth/logout/", views.logout_view, name="logout"),
]
