"""
Django settings for the RAG-USTHB backend.
Configuration is loaded from the root .env file.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


# --------------------------------------------------
# Paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
PREPROCESSING_DIR = REPO_ROOT / "preprocessing"

# Repo root: `rag.*`. Preprocessing: `core.models`, `parsers`, `pipeline`.
# Append, never insert: Django's `config` package must stay first on sys.path.
for _path in (REPO_ROOT, PREPROCESSING_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.append(_path_str)

# Load RAG-USTHB/.env
ENV_FILE = REPO_ROOT / ".env"
load_dotenv(ENV_FILE)

# Optional per-environment overrides, loaded second so it can fill in anything
# the root file leaves unset. This is where the LLM credentials are meant to
# live (``backend/.env``); it is matched by the ``.env*`` ignore rule, so a
# real key can never be committed. Absent file -> nothing happens.
load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------
# Environment helpers
# --------------------------------------------------

def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    value = env_str(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# --------------------------------------------------
# Environment
# --------------------------------------------------

ENVIRONMENT = env_str("DJANGO_ENV", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

if ENVIRONMENT not in {"development", "production"}:
    raise ImproperlyConfigured(
        "DJANGO_ENV must be development or production."
    )


# --------------------------------------------------
# Security
# --------------------------------------------------

SECRET_KEY = env_str("SECRET_KEY")

if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured(
            "SECRET_KEY is required in production."
        )

    SECRET_KEY = (
        "django-insecure-DEV-ONLY-KEY-do-not-use-in-production"
    )

    warnings.warn(
        "SECRET_KEY is not set. Using a development-only key.",
        RuntimeWarning,
    )

DEBUG = False if IS_PRODUCTION else env_bool("DEBUG", True)

#: The Next.js dev server proxies /api/* to Django (see frontend/next.config.mjs)
#: so that session + CSRF cookies stay first-party. Depending on the proxy
#: implementation the Host header reaching Django is either the Next origin or
#: the Django origin, so both are accepted in development.
ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1],testserver,"
    "localhost:3000,127.0.0.1:3000,"
    "localhost:3001,127.0.0.1:3001,"
    "localhost:3100,127.0.0.1:3100,"
    "127.0.0.1:8000"
    if not IS_PRODUCTION
    else "",
)

if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS is required in production."
    )


#: Origin(s) allowed to send cross-site POSTs (CSRF). In development the
#: Next.js dev server is the only client; in production set FRONTEND_ORIGIN to
#: the deployed frontend URL.
#: NOTE: if FRONTEND_ORIGIN is set in .env, it REPLACES these defaults.
CSRF_TRUSTED_ORIGINS = env_list(
    "FRONTEND_ORIGIN",
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3001,http://127.0.0.1:3001,"   # <-- FIX: port 3001 added
    "http://localhost:3100,http://127.0.0.1:3100"
    if not IS_PRODUCTION
    else "",
)


# --------------------------------------------------
# Database: Supabase PostgreSQL or local SQLite
# --------------------------------------------------

DB_NAME = env_str("DB_NAME")
DB_USER = env_str("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = env_str("DB_HOST")
DB_PORT = env_str("DB_PORT", "5432")

DB_VALUES = [DB_NAME, DB_USER, DB_PASSWORD, DB_HOST]
DB_CONFIGURED = all(DB_VALUES)

if IS_PRODUCTION and not DB_CONFIGURED:
    raise ImproperlyConfigured(
        "Set DB_NAME, DB_USER, DB_PASSWORD and DB_HOST "
        "in the environment."
    )

if DB_CONFIGURED:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT,
            "OPTIONS": {
                "sslmode": "require",
            },
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }

    USING_POSTGRES = True

else:
    if any(DB_VALUES):
        warnings.warn(
            "Some database variables are missing. "
            "Using SQLite in development.",
            RuntimeWarning,
        )
    else:
        warnings.warn(
            "PostgreSQL variables are not configured. "
            "Using local SQLite in development.",
            RuntimeWarning,
        )

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

    USING_POSTGRES = False


# --------------------------------------------------
# Applications
# --------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Project apps. Add API packages (e.g. rest_framework) back here when the
    # features they back are actually implemented.
    "rest_framework",
    "users",
    "chatbot",
]

if USING_POSTGRES:
    INSTALLED_APPS.append("django.contrib.postgres")


# --------------------------------------------------
# Middleware
# --------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# --------------------------------------------------
# URLs and application
# --------------------------------------------------

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# --------------------------------------------------
# Templates
# --------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# -------------------------------------------------
# Password validation
# -------------------------------------------------
# RAG-USTHB policy (see the project spec): a student password is **exactly 8
# digits**, i.e. a numeric PIN. Two of Django's stock validators are therefore
# deliberately disabled rather than fought with at every call site:
#
#   * NumericPasswordValidator - rejects any all-numeric password, which would
#     reject *every* valid RAG-USTHB password.
#   * CommonPasswordValidator  - its blocklist contains "12345678", which is a
#     legitimate 8-digit PIN under this policy.
#
# MinimumLengthValidator stays (a PIN shorter than 8 is rejected), and
# UserAttributeSimilarityValidator stays (a PIN equal to the student's own
# matricule/e-mail is still refused). Django's `set_password` hashes with
# PBKDF2-SHA256 regardless of which validators are configured, so storage
# remains salted and irreversible.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
        "OPTIONS": {"min_length": 8},
    },
]


# -------------------------------------------------
# Django REST framework
# -------------------------------------------------
# Session authentication only: the browser talks to /api/* through the Next.js
# proxy on the same origin, so Django's session + CSRF cookies are first-party
# and no token is ever stored in localStorage.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        # Every endpoint is private unless it opts out explicitly (register,
        # login, logout, csrf).
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}


# --------------------------------------------------
# Production security
# --------------------------------------------------

if IS_PRODUCTION:
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"


# --------------------------------------------------
# Internationalisation
# --------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Algiers"

USE_I18N = True
USE_TZ = True


# --------------------------------------------------
# Static files
# --------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# --------------------------------------------------
# Default primary key
# --------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------
# Logging
# --------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "%(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}