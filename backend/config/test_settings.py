"""Settings for running the test suite locally.

Why this file exists
--------------------
``config/settings.py`` resolves to the project's PostgreSQL instance when the
``DB_*`` variables are set. Django's test runner needs to *create* a throwaway
database (``test_<name>``), which on a managed host such as Supabase is either
forbidden or requires privileges nobody should hand to a test suite.

So the suite runs against a local SQLite file instead. The chatbot migration
``0001`` was written for exactly this: ``pgvector.django.VectorExtension``
short-circuits when ``connection.vendor != "postgresql"``, so the SQLite test
database needs neither pgvector nor a Postgres server.

Usage::

    .venv\\Scripts\\python.exe manage.py test --settings=config.test_settings

Nothing here changes what production runs - it only overrides the database.
"""

from __future__ import annotations

from .settings import *  # noqa: F401,F403 - inherit everything, override below

# Keep the throwaway database out of the real one's way.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",  # noqa: F405
    }
}

# Tests exercise password validation and CSRF explicitly; the noisy
# "unencrypted password" / security warnings only obscure the real output.
SILENCED_SYSTEM_CHECKS = ["security.W003", "security.W012"]
