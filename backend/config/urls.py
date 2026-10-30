"""Root URL configuration for the RAG-USTHB backend.

Route map
---------
``/admin/``          Django admin (session based).
``/api/auth/``       Registration, login, logout, current session, CSRF seed.
``/api/chat/``       Conversations and RAG question/answer - authenticated.

Both API trees are served under ``/api/`` on the Django origin. The browser
never talks to Django directly in development: ``frontend/next.config.mjs``
proxies ``/api/*`` there, so the session and CSRF cookies stay first-party and
no CORS layer is needed.
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "api/auth/",
        include(("users.urls", "users"), namespace="users"),
    ),
    path(
        "api/chat/",
        include(("chatbot.urls", "chatbot"), namespace="chatbot"),
    ),
]
