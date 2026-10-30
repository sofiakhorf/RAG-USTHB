"""Account validation rules for RAG-USTHB.

These are the *only* place the university e-mail domain and the PIN format are
defined on the backend. The frontend mirrors them for instant feedback, but the
frontend is never trusted: every rule below also runs here, on the server, at
registration time.

Policy (from the project specification):

* A student account is identified by a **university e-mail** whose domain is
  exactly ``etu.usthb.dz``.
* A student password is **exactly 8 digits** - a numeric PIN, never a
  passphrase. Hence :func:`validate_pin` and the trimmed
  ``AUTH_PASSWORD_VALIDATORS`` in ``config/settings.py``.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

__all__ = [
    "MAX_MATRICULE_LENGTH",
    "MIN_FULL_NAME_LENGTH",
    "PASSWORD_LENGTH",
    "UNIVERSITY_EMAIL_DOMAIN",
    "validate_full_name",
    "validate_matricule",
    "validate_pin",
    "validate_university_email",
]

#: The only domain a student may register with.
UNIVERSITY_EMAIL_DOMAIN = "etu.usthb.dz"

#: Length of the numeric PIN. Exactly this many digits - no more, no less.
PASSWORD_LENGTH = 8

#: A matricule is a short administrative number; the model caps it at 30.
MAX_MATRICULE_LENGTH = 30

#: "Jean Dupont" is two characters; a single letter is not a name.
MIN_FULL_NAME_LENGTH = 2

# ``something@etu.usthb.dz`` - exactly one "@", no whitespace, exact domain.
# ``re.IGNORECASE`` so "Jean@ETU.USTHB.DZ" is accepted, then normalised to
# lower case by the caller.
_EMAIL_RE = re.compile(
    rf"^[^@\s]+@{re.escape(UNIVERSITY_EMAIL_DOMAIN)}$",
    re.IGNORECASE,
)

# Exactly eight ASCII digits. ``\d`` in Python also matches Unicode digits
# (Arabic-Indic "١٢٣٤٥٦٧٨"), so ``[0-9]`` is used deliberately: a PIN must be
# typed on a digit keypad.
_PIN_RE = re.compile(rf"^[0-9]{{{PASSWORD_LENGTH}}}$")


def validate_university_email(value: str) -> str:
    """Return the normalised e-mail, or raise :class:`ValidationError`.

    Args:
        value: Raw e-mail as typed by the student.

    Returns:
        The e-mail lower-cased, so ``Jean@ETU.USTHB.DZ`` and
        ``jean@etu.usthb.dz`` cannot create two accounts.

    Raises:
        ValidationError: Blank, malformed, or not an ``@etu.usthb.dz`` address.
    """
    candidate = (value or "").strip()

    if not candidate:
        raise ValidationError("University e-mail is required.")

    if not _EMAIL_RE.match(candidate):
        raise ValidationError(
            f"Use your university e-mail ending with @{UNIVERSITY_EMAIL_DOMAIN}."
        )

    return candidate.lower()


def validate_pin(value: str) -> str:
    """Validate the numeric PIN.

    Args:
        value: Raw password as typed.

    Returns:
        The PIN, unchanged, on success.

    Raises:
        ValidationError: If it is not exactly 8 digits.
    """
    candidate = value or ""

    if not candidate:
        raise ValidationError("Password is required.")

    if not _PIN_RE.match(candidate):
        raise ValidationError(
            f"The password must be exactly {PASSWORD_LENGTH} digits "
            "(numbers only, no letters, spaces or symbols)."
        )

    return candidate


def validate_full_name(value: str) -> str:
    """Validate the student's full name.

    Args:
        value: Raw full name as typed.

    Returns:
        The name with runs of whitespace collapsed to single spaces.

    Raises:
        ValidationError: If blank or shorter than
            :data:`MIN_FULL_NAME_LENGTH` characters.
    """
    candidate = " ".join((value or "").split())

    if len(candidate) < MIN_FULL_NAME_LENGTH:
        raise ValidationError("Full name is required.")

    return candidate


def validate_matricule(value: str) -> str:
    """Validate the student registration number (matricule).

    Args:
        value: Raw matricule as typed.

    Returns:
        The matricule, trimmed.

    Raises:
        ValidationError: If blank or longer than
            :data:`MAX_MATRICULE_LENGTH` characters.
    """
    candidate = (value or "").strip()

    if not candidate:
        raise ValidationError("Student registration number (matricule) is required.")

    if len(candidate) > MAX_MATRICULE_LENGTH:
        raise ValidationError(
            f"Matricule must be at most {MAX_MATRICULE_LENGTH} characters."
        )

    return candidate
