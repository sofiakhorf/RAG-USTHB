"""Serializers for the RAG-USTHB account API.

Two shapes live here:

* :class:`RegisterSerializer` - validates the signup form and creates the
  ``auth.User`` + :class:`chatbot.StudentProfile` pair.
* :func:`public_user_payload` - the single projection returned to the browser.

Why a ``Serializer`` and not ``ModelSerializer``
------------------------------------------------
The signup form spans **two** models (``auth.User`` for the credentials and
``StudentProfile`` for matricule/department), and ``auth.User`` is a Django
built-in that must not be sub-classed for an MVP. A plain ``Serializer`` can
express that split honestly, whereas a ``ModelSerializer`` would have to be
forced onto one of the two models.

Security note
-------------
:func:`public_user_payload` is the *only* user projection the API exposes. It
never includes ``password`` or ``password_hash`` - the raw ``User`` object is
never serialised by accident, because it is never handed to a
``ModelSerializer``.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from chatbot.models import StudentProfile

from .validators import (
    validate_full_name,
    validate_matricule,
    validate_pin,
    validate_university_email,
)

__all__ = ["PublicUserSerializer", "RegisterSerializer", "public_user_payload"]

User = get_user_model()

#: Machine-readable keys the frontend maps to localised copy. Kept in sync with
#: :mod:`users.validators` so a rejected field is always identifiable without
#: the client parsing an English sentence.
PASSWORD_MISMATCH = "password_mismatch"
PASSWORD_POLICY = "password_policy"
EMAIL_TAKEN = "email_taken"
MATRICULE_TAKEN = "matricule_taken"
UNKNOWN_DEPARTMENT = "unknown_department"


def _first_django_message(exc: DjangoValidationError) -> str:
    """Pull the first readable message out of a Django ``ValidationError``.

    Django's ``ValidationError`` carries messages in three shapes: a bare list
    of strings, a dict keyed by field, or a nested list per key. The password
    validators raise all three, so flattening here means the caller always gets
    a sentence to show a student rather than a ``repr``.

    Args:
        exc: The caught ``ValidationError``.

    Returns:
        The first message found, or ``""`` when it carried none.
    """
    messages: list[str] = []

    if hasattr(exc, "message_dict"):
        for field_messages in exc.message_dict.values():
            messages.extend(field_messages)
    elif hasattr(exc, "messages"):
        messages.extend(exc.messages)

    return messages[0] if messages else ""


def split_full_name(full_name: str) -> tuple[str, str]:
    """Split a full name into Django's ``first_name`` / ``last_name``.

    ``auth.User`` stores two name columns, but the signup form asks for one
    "Full name". ``auth.User.first_name`` is therefore treated as *the rest of
    the name* rather than strictly the given name, so nothing is lost::

        >>> split_full_name("Jean Dupont")
        ('Jean', 'Dupont')
        >>> split_full_name("Amina Benali")
        ('Amina', 'Benali')

    Args:
        full_name: Already-normalised full name (single spaces, trimmed).

    Returns:
        A ``(first_name, last_name)`` tuple; ``last_name`` is ``""`` when the
        student supplied a single word.
    """
    parts = full_name.split(maxsplit=1)

    if len(parts) == 1:
        return parts[0], ""

    return parts[0], parts[1]


def public_user_payload(user) -> dict:
    """Project a ``User`` onto the shape the frontend consumes.

    Args:
        user: A :class:`django.contrib.auth.models.User` instance.

    Returns:
        ``{"id", "full_name", "matricule", "department", "email"}``. The
        password and its hash are structurally absent - see the module
        docstring.

    Notes:
        ``StudentProfile`` is an optional ``OneToOneField``, so a user created
        through ``createsuperuser`` (or the admin) may legitimately have none;
        the profile fields then degrade to empty strings instead of raising.
    """
    profile = getattr(user, "student_profile", None)

    return {
        "id": str(user.pk),
        "full_name": user.get_full_name() or user.username,
        "matricule": getattr(profile, "matricule", "") if profile else "",
        "department": getattr(profile, "department", "") if profile else "",
        "email": user.email,
    }


class PublicUserSerializer(serializers.Serializer):
    """Read-only projection of the authenticated student.

    Mirrors :func:`public_user_payload`; used only for typed access on the
    backend side, never as an input.
    """

    id = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    matricule = serializers.CharField(read_only=True)
    department = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)


class RegisterSerializer(serializers.Serializer):
    """Validates the signup form and creates the account.

    Every field rule is delegated to :mod:`users.validators`, so the browser
    and the server apply *identical* constraints even though only the server
    one is authoritative.

    Raises:
        ValidationError: With a per-field message list, which DRF renders as
            ``{"<field>": ["<message>", ...]}`` - the shape the frontend maps
            onto its localised error display.
    """

    full_name = serializers.CharField(required=True, trim_whitespace=True)
    matricule = serializers.CharField(required=True, trim_whitespace=True)
    department = serializers.ChoiceField(
        choices=StudentProfile.DEPARTMENTS,
        error_messages={
            "invalid_choice": (
                "Choose one of the departments listed in the form."
            ),
            "required": "Department is required.",
        },
    )
    email = serializers.EmailField(required=True, trim_whitespace=True)
    password = serializers.CharField(required=True, write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(
        required=True, write_only=True, trim_whitespace=False
    )

    # -- field-level validation -----------------------------------------

    def validate_full_name(self, value: str) -> str:
        """Apply :func:`validate_full_name`."""
        return validate_full_name(value)

    def validate_matricule(self, value: str) -> str:
        """Apply :func:`validate_matricule`, then enforce uniqueness.

        ``StudentProfile.matricule`` is ``unique=True`` at the database level,
        so this check is a courtesy (a clear message now) layered on top of a
        hard constraint (a race-safe ``IntegrityError`` later).

        Args:
            value: Raw matricule.

        Returns:
            The trimmed matricule.

        Raises:
            ValidationError: If already registered to another student.
        """
        candidate = validate_matricule(value)

        if StudentProfile.objects.filter(matricule__iexact=candidate).exists():
            raise serializers.ValidationError(
                {
                    "matricule": (
                        "This registration number is already linked to an "
                        "account. Use Login instead, or contact administration "
                        "if you believe this is an error."
                    )
                },
                code=MATRICULE_TAKEN,
            )

        return candidate

    def validate_department(self, value: str) -> str:
        """Pass :class:`ChoiceField`'s own validation through unchanged.

        Args:
            value: The department key, e.g. ``computer_science``.

        Returns:
            The department key, unchanged.
        """
        return value

    def validate_email(self, value: str) -> str:
        """Apply the university domain rule, then enforce uniqueness.

        Args:
            value: Raw e-mail as typed.

        Returns:
            The normalised (lower-cased) e-mail.

        Raises:
            ValidationError: If the domain is wrong, or the e-mail already
                belongs to an account. Both ``email`` and ``username`` are
                checked, because the username is set to the e-mail to keep
                Django's built-in ``User`` usable without a custom model.
        """
        candidate = validate_university_email(value)

        # ``auth.User`` has no unique constraint on ``email`` by default, so
        # uniqueness is enforced here and, redundantly, on ``username`` below
        # (``username`` *is* unique at the database level).
        if User.objects.filter(email__iexact=candidate).exists():
            raise serializers.ValidationError(
                {
                    "email": (
                        "An account already exists for this university "
                        "e-mail. Use Login instead."
                    )
                },
                code=EMAIL_TAKEN,
            )

        if User.objects.filter(username__iexact=candidate).exists():
            raise serializers.ValidationError(
                {
                    "email": (
                        "An account already exists for this university "
                        "e-mail. Use Login instead."
                    )
                },
                code=EMAIL_TAKEN,
            )

        return candidate

    def validate_password(self, value: str) -> str:
        """Apply :func:`validate_pin` (exactly 8 digits)."""
        return validate_pin(value)

    def validate_confirm_password(self, value: str) -> str:
        """Validate the confirmation is a well-formed PIN.

        The *match* check lives in :meth:`validate`, because it needs the
        sibling ``password`` field.

        Args:
            value: Raw confirmation as typed.

        Returns:
            The confirmation, unchanged.

        Raises:
            ValidationError: If it is not exactly 8 digits.
        """
        return validate_pin(value)

    # -- object-level validation ----------------------------------------

    def validate(self, attrs: dict) -> dict:
        """Check the two password fields agree.

        Args:
            attrs: Already field-validated attributes.

        Returns:
            ``attrs``, unchanged.

        Raises:
            ValidationError: With ``confirm_password`` set, when the two
                values differ. Attached to the confirmation field so the
                browser can highlight the right input.
        """
        password = attrs.get("password", "")
        confirm = attrs.get("confirm_password", "")

        if password != confirm:
            raise serializers.ValidationError(
                {"confirm_password": "The two passwords do not match."},
                code=PASSWORD_MISMATCH,
            )

        return attrs

    # -- creation -------------------------------------------------------

    def create(self, validated_data: dict):
        """Create the ``User`` and its :class:`StudentProfile` atomically.

        Args:
            validated_data: Attributes produced by the validators above.

        Returns:
            The newly created :class:`~django.contrib.auth.models.User`.

        Notes:
            * The e-mail doubles as the **username**, which is what gives the
              uniqueness guarantee for free and lets
              ``authenticate(username=email, ...)`` work with Django's stock
              user model - no custom ``AUTH_USER_MODEL``, no extra migration.
            * ``transaction.atomic`` so a failure after the ``User`` insert
              cannot leave an orphaned account with no profile.
            * ``validate_password`` is Django's own policy check; the stock
              validators were tuned in ``settings.py`` so an 8-digit PIN is
              accepted while short or identity-derived PINs still fail.
        """
        email = validated_data["email"]
        full_name = validated_data["full_name"]
        first_name, last_name = split_full_name(full_name)

        user = User(
            username=email,  # username == e-mail; see the docstring
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        # ``set_password`` applies PBKDF2-SHA256 with a per-user salt. The PIN
        # is never written to the database in clear text.
        user.set_password(validated_data["password"])

        # Run Django's configured AUTH_PASSWORD_VALIDATORS against the *whole*
        # user, so UserAttributeSimilarityValidator can compare the PIN to the
        # student's own matricule/name.
        #
        # ``validate_password`` raises Django's ``ValidationError``, not DRF's,
        # and DRF's exception handler only understands its own exception types
        # - so an uncaught one escapes as a raw ``500`` HTML page. That is a
        # reachable outcome, not a theoretical one: a PIN that resembles the
        # digits in the student's own e-mail trips the similarity validator.
        # Translating it here keeps the response a clean ``400`` attached to
        # the field the browser should highlight.
        try:
            validate_password(validated_data["password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"password": _first_django_message(exc) or "Choose a different password."},
                code=PASSWORD_POLICY,
            ) from exc

        with transaction.atomic():
            user.save()

            StudentProfile.objects.create(
                user=user,
                matricule=validated_data["matricule"],
                department=validated_data["department"],
                role="student",
            )

        return user
