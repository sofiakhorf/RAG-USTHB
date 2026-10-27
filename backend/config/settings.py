
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

if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

# Load RAG-USTHB/.env
ENV_FILE = REPO_ROOT / ".env"
load_dotenv(ENV_FILE)


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

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1],testserver"
    if not IS_PRODUCTION
    else "",
)

if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS is required in production."
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


# --------------------------------------------------
# Password validation
# --------------------------------------------------

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
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


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
