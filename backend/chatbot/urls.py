"""URL map for ``/api/chat/``.

A ``SimpleRouter`` rather than ``DefaultRouter``: the latter also emits an API
root index and a format-suffix pattern, neither of which this SPA consumes, and
the root index would add an extra authenticated endpoint nobody asked for.
"""

from __future__ import annotations

from rest_framework.routers import SimpleRouter

from .views import ChatSessionViewSet

app_name = "chatbot"

router = SimpleRouter()
router.register(
    r"sessions",
    ChatSessionViewSet,
    basename="chat-session",
)

urlpatterns = router.urls
