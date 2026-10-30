"""HTTP endpoints for registration, login, logout and the current session.

Wiring
------
``config/urls.py`` mounts these under ``/api/auth/``, and
``frontend/next.config.mjs`` proxies the browser's ``/api/*`` onto Django.
Because the browser and Django therefore share one origin, the **session
cookie** is first-party: authentication is a plain Django session, and no token
is ever written to ``localStorage``.

CSRF
----
Login and registration are wrapped with ``csrf_protect`` via
``@method_decorator(..., name="dispatch")`` - DRF's ``SessionAuthentication``
only enforces CSRF for *already authenticated* requests, which would leave these
two endpoints open to cross-site request forgery (a "login CSRF" attack).

The decorator must target ``dispatch``, not the result of ``as_view()``.
``APIView.as_view()`` deliberately stamps ``view.csrf_exempt = True`` on the
view it returns, and ``CsrfViewMiddleware.process_view`` honours that flag - so
``csrf_protect(SomeView.as_view())`` compiles, runs, and silently protects
nothing. Targeting the method instead passes an unmarked callback to the
middleware, which is what makes the check actually fire.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import PublicUserSerializer, RegisterSerializer, public_user_payload
from .validators import validate_university_email

__all__ = [
    "CSRFView",
    "CurrentUserView",
    "LoginView",
    "LogoutView",
    "RegisterView",
]

User = get_user_model()

#: Returned verbatim by login/register. Deliberately vague about *which* of the
#: two inputs was wrong, so the endpoint cannot be used to enumerate valid
#: university e-mails.
INVALID_CREDENTIALS = "Incorrect e-mail or password."


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CSRFView(APIView):
    """Seed the CSRF cookie the browser echoes back on every POST.

    ``GET /api/auth/csrf/``

    The response sets Django's ``csrftoken`` cookie. The frontend reads it and
    sends it as the ``X-CSRFToken`` header, which ``csrf_protect`` then
    verifies.

    ``authentication_classes`` is emptied on purpose: nothing about this
    endpoint depends on who is asking, and skipping authentication keeps the
    session untouched so an anonymous visitor can bootstrap the token before
    logging in.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        """Set the CSRF cookie and acknowledge it.

        Args:
            request: The incoming request.

        Returns:
            ``200`` with ``{"detail": ...}``.
        """
        return Response({"detail": "CSRF cookie set."})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    """Create a student account.

    ``POST /api/auth/register``

    Body:
        ``full_name``, ``matricule``, ``department``, ``email``,
        ``password``, ``confirm_password``.

    Returns:
        ``201`` with the public projection of the new account. The caller is
        **not** logged in - the specification asks for a redirect to Login
        after registration, so the session is deliberately left anonymous.

    Raises:
        ``400`` with a per-field ``{"<field>": ["<message>"]}`` object when any
        rule is broken, including a duplicate e-mail or matricule.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        """Validate the form and create the account.

        Args:
            request: The incoming request; ``request.data`` holds the form.

        Returns:
            ``201`` + ``{"detail", "user"}``, or ``400`` + field errors.
        """
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        return Response(
            {
                "detail": "Account created. You can now log in.",
                "user": public_user_payload(user),
            },
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """Authenticate a student and start a session.

    ``POST /api/auth/login``

    Body:
        ``email`` (the university e-mail) and ``password``.

    Returns:
        ``200`` with the public projection. Django's session middleware sets
        the ``sessionid`` cookie as a side effect of
        :func:`~django.contrib.auth.login`.

    Raises:
        ``400``: the e-mail is not an ``@etu.usthb.dz`` address.
        ``401``: no matching account, or the PIN is wrong.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        """Look the student up and start their session.

        Args:
            request: The incoming request; ``request.data`` holds the form.

        Returns:
            ``200`` + ``{"detail", "user"}``, or ``400``/``401`` + ``{"detail"}``.
        """
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""

        # Domain rule is re-applied on login, not only at registration, so the
        # endpoint cannot be used to probe arbitrary addresses.
        try:
            email = validate_university_email(email)
        except Exception as exc:  # django.core.exceptions.ValidationError
            return Response(
                {"detail": str(exc.messages[0])},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not password:
            return Response(
                {"detail": "Password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ``username`` is set to the e-mail at registration (see
        # RegisterSerializer.create), so authenticating by username authenticates
        # by e-mail while staying on Django's stock user model.
        user = authenticate(request, username=email, password=password)

        if user is None:
            # Same message for "unknown e-mail" and "wrong PIN" - see
            # INVALID_CREDENTIALS.
            return Response(
                {"detail": INVALID_CREDENTIALS},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Rotates the session key, which defeats session fixation: a session id
        # captured before login cannot be reused after it.
        login(request, user)

        return Response(
            {
                "detail": "Logged in.",
                "user": public_user_payload(user),
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    """End the current session.

    ``POST /api/auth/logout``

    Returns:
        ``200``. ``logout()`` flushes the session server-side *and* expires the
        browser's ``sessionid`` cookie, so the id is worthless even if it was
        observed. ``AllowAny`` is used because logging out must succeed for an
        already-expired session too - a stale tab should not get a 403.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        """Flush the session.

        Args:
            request: The incoming request.

        Returns:
            ``200`` with ``{"detail": ...}``.
        """
        # ``request._request`` is the underlying HttpRequest; passing it avoids
        # relying on DRF's Request proxying the ``session`` attribute.
        logout(request._request)

        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """Describe the signed-in student.

    ``GET /api/auth/me``

    Used by the frontend's auth guard on every protected page load, so it is
    the endpoint that decides whether a direct URL hit on ``/chat`` or
    ``/profile`` is allowed.

    Returns:
        ``200`` + the public projection when a session exists, otherwise
        ``401``. ``401`` (not ``403``) is returned explicitly rather than via
        ``IsAuthenticated`` so the browser can tell "not signed in" apart from
        "signed in but forbidden".

    Notes:
        The default authentication classes are kept. ``authentication_classes``
        must **not** be emptied here: with no authenticator configured DRF has
        nothing to resolve ``request.user`` from and falls back to
        ``UNAUTHENTICATED_USER`` (``None``), so a perfectly valid session cookie
        would be ignored and every caller would look anonymous. ``AllowAny``
        keeps anonymous callers from being rejected outright so this view can
        answer ``401`` itself. The CSRF that ``SessionAuthentication``
        enforces is a no-op on GET, because safe methods are always accepted.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        """Return the current user, or ``401``.

        Args:
            request: The incoming request.

        Returns:
            ``Response``: ``200`` + public projection, or ``401`` + ``{"detail"}``.
        """
        user = request.user

        if user is None or not user.is_authenticated:
            return Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = public_user_payload(user)
        serializer = PublicUserSerializer(payload)

        return Response({"user": serializer.data}, status=status.HTTP_200_OK)
