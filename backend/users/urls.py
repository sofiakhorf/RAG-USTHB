"""URL map for ``/api/auth/``.

CSRF is enforced on the views themselves (``@method_decorator(csrf_protect,
name="dispatch")``) rather than here. Wrapping ``as_view()`` at this level looks
equivalent but is not: DRF stamps ``csrf_exempt`` on the function ``as_view()``
returns, and ``CsrfViewMiddleware`` honours that flag, so a URLconf-level wrap
would silently protect nothing. See :mod:`users.views`.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("csrf/", views.CSRFView.as_view(), name="csrf"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.CurrentUserView.as_view(), name="me"),
]
