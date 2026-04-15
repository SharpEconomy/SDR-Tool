from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None, default: list[str]) -> list[str]:
    items: list[str] = list(default)
    if not value:
        return items

    for item in value.split(","):
        normalized = item.strip()
        if normalized and normalized not in items:
            items.append(normalized)

    return items


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-before-production",
)
DEBUG = _as_bool(os.getenv("DJANGO_DEBUG"), True)
ALLOWED_HOSTS = _as_list(
    os.getenv("DJANGO_ALLOWED_HOSTS"),
    ["localhost", "testserver", "sdr.buildwithai.ai"],
)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "growth_engine_web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "growth_engine_django.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
                "django.contrib.messages.context_processors.messages",
                "growth_engine_web.context_processors.app_shell",
            ],
        },
    }
]

WSGI_APPLICATION = "growth_engine_django.wsgi.application"

# Firestore remains the only database in the product. Django state is kept in files/cookies.
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

SESSION_ENGINE = "django.contrib.sessions.backends.file"
SESSION_FILE_PATH = str(BASE_DIR / ".django_sessions")
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

os.makedirs(SESSION_FILE_PATH, exist_ok=True)
