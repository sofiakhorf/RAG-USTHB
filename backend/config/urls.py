"""Root URL configuration for the RAG-USTHB backend.

Route map
---------
``/admin/``    Django admin (session based).

No application API routes are mounted yet: this repository currently ships a
**scaffold only**. When you implement the features, register them here::

    from django.urls import include, path

    urlpatterns = [
        path("admin/", admin.site.urls),
        path("api/auth/", include(("users.urls", "users"), namespace="users")),
        path("api/", include(("chatbot.urls", "chatbot"), namespace="chatbot")),
    ]
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
