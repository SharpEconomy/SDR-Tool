from __future__ import annotations

from django.urls import path

from growth_engine_web import views

app_name = "growth_engine_web"

urlpatterns = [
    path("", views.home, name="home"),
    path("research/", views.research_profile, name="research"),
    path("edit/<str:card_id>/", views.edit_section, name="edit_section"),
    path("save/", views.save_profile, name="save_profile"),
    path("request-data/", views.request_data, name="request_data"),
    path("auth/firebase/", views.firebase_login, name="firebase_login"),
    path("auth/logout/", views.logout_view, name="logout"),
]
