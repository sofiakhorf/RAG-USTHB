"""Tests for the registration / login / session API.

Run with::

    .venv\\Scripts\\python.exe manage.py test --settings=config.test_settings

These cover the two things that are easy to get silently wrong and expensive to
get wrong in production:

* **Validation is enforced server-side.** The frontend mirrors the rules, but
  every assertion here calls the HTTP API directly with no browser in the way,
  so a broken client-side check cannot make these pass.
* **The password never leaves the server in clear text**, neither in the
  database nor in a response body.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from chatbot.models import StudentProfile

User = get_user_model()

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/auth/me/"
CSRF_URL = "/api/auth/csrf/"

VALID_EMAIL = "amina.benali@etu.usthb.dz"

VALID_REGISTRATION = {
    "full_name": "Amina Benali",
    "matricule": "202331045678",
    "department": "computer_science",
    "email": VALID_EMAIL,
    "password": "49170238",
    "confirm_password": "49170238",
}


def make_registration(**overrides):
    """Return a copy of the valid signup payload with ``overrides`` applied."""
    payload = dict(VALID_REGISTRATION)
    payload.update(overrides)
    return payload


class RegistrationTests(APITestCase):
    """``POST /api/auth/register``."""

    def test_valid_registration_creates_user_and_profile(self):
        """A well-formed form creates both rows and returns ``201``."""
        response = self.client.post(
            REGISTER_URL, VALID_REGISTRATION, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(StudentProfile.objects.count(), 1)

        user = User.objects.get()
        self.assertEqual(user.email, VALID_EMAIL)
        # The e-mail doubles as the username, which is what gives the unique
        # constraint on registration.
        self.assertEqual(user.username, VALID_EMAIL)
        self.assertEqual(user.get_full_name(), "Amina Benali")

        profile = user.student_profile
        self.assertEqual(profile.matricule, "202331045678")
        self.assertEqual(profile.department, "computer_science")
        self.assertEqual(profile.role, "student")

    def test_password_is_hashed_not_stored_in_clear(self):
        """The PIN must be unreadable in the database."""
        self.client.post(REGISTER_URL, VALID_REGISTRATION, format="json")

        user = User.objects.get()
        stored = user.password

        self.assertNotEqual(stored, VALID_REGISTRATION["password"])
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        # The clear-text PIN must not appear anywhere in the stored value...
        self.assertNotIn(VALID_REGISTRATION["password"], stored)
        # ...but the hash must still verify against it, i.e. it is a real
        # hash of this PIN and not just a random string.
        self.assertTrue(user.check_password(VALID_REGISTRATION["password"]))
        self.assertFalse(user.check_password("00000000"))

    def test_registration_does_not_create_a_session(self):
        """Registration must leave the browser anonymous, ready for Login."""
        response = self.client.post(
            REGISTER_URL, VALID_REGISTRATION, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # `self.client` is a shared cookie jar, so an accidental login() would
        # leave a sessionid behind.
        self.assertNotIn("sessionid", self.client.cookies)

    def test_response_never_contains_the_password(self):
        """Neither the PIN nor its hash may appear in the payload."""
        response = self.client.post(
            REGISTER_URL, VALID_REGISTRATION, format="json"
        )

        body = response.content.decode()

        self.assertNotIn(VALID_REGISTRATION["password"], body)
        self.assertNotIn("password", response.data["user"])

    # -- e-mail domain --------------------------------------------------

    def test_non_university_domain_is_rejected(self):
        """Only ``@etu.usthb.dz`` addresses may register."""
        response = self.client.post(
            REGISTER_URL,
            make_registration(email="amina@gmail.com"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertIn(VALID_EMAIL.rsplit("@", 1)[1], str(response.data["email"]))
        self.assertEqual(User.objects.count(), 0)

    def test_main_university_domain_is_rejected(self):
        """``@usthb.dz`` (staff) is *not* the student domain."""
        response = self.client.post(
            REGISTER_URL,
            make_registration(email="prof@usthb.dz"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), 0)

    def test_university_email_is_normalised_to_lowercase(self):
        """``Jean@ETU.USTHB.DZ`` and ``jean@etu.usthb.dz`` are one account."""
        self.client.post(
            REGISTER_URL,
            make_registration(email="AMINA.BENALI@ETU.USTHB.DZ"),
            format="json",
        )

        self.assertEqual(User.objects.get().email, VALID_EMAIL)

    # -- password format ------------------------------------------------

    def test_password_with_letters_is_rejected(self):
        """Exactly 8 digits - a letter anywhere is invalid."""
        response = self.client.post(
            REGISTER_URL,
            make_registration(password="4917a238", confirm_password="4917a238"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_password_with_seven_or_nine_digits_is_rejected(self):
        """The length is exact, not a minimum."""
        for pin in ("4917023", "491702389"):
            response = self.client.post(
                REGISTER_URL,
                make_registration(password=pin, confirm_password=pin),
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"PIN {pin!r} should have been rejected",
            )

        self.assertEqual(User.objects.count(), 0)

    def test_password_with_spaces_or_symbols_is_rejected(self):
        """No spaces, no punctuation - digits only."""
        for pin in ("4917 023", "4917-238", "4917023!"):
            response = self.client.post(
                REGISTER_URL,
                make_registration(password=pin, confirm_password=pin),
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"PIN {pin!r} should have been rejected",
            )

    def test_mismatched_confirmation_is_rejected(self):
        """The two password fields must agree."""
        response = self.client.post(
            REGISTER_URL,
            make_registration(password="49170238", confirm_password="87302194"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)
        self.assertEqual(User.objects.count(), 0)

    # -- uniqueness -----------------------------------------------------

    def test_duplicate_email_is_rejected(self):
        """A second registration with the same e-mail must fail clearly."""
        first = self.client.post(REGISTER_URL, VALID_REGISTRATION, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(
            REGISTER_URL,
            make_registration(matricule="202399999999"),
            format="json",
        )

        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", second.data)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_email_differs_only_by_case(self):
        """Case-folding happens before the uniqueness check."""
        self.client.post(REGISTER_URL, VALID_REGISTRATION, format="json")

        response = self.client.post(
            REGISTER_URL,
            make_registration(
                email="Amina.Benali@ETU.USTHB.DZ",
                matricule="202399999999",
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_matricule_is_rejected(self):
        """A matricule belongs to exactly one student."""
        self.client.post(REGISTER_URL, VALID_REGISTRATION, format="json")

        response = self.client.post(
            REGISTER_URL,
            make_registration(email="yacine.hamdi@etu.usthb.dz"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("matricule", response.data)
        self.assertEqual(User.objects.count(), 1)

    # -- presence -------------------------------------------------------

    def test_missing_required_field_is_rejected(self):
        """Every field on the form is required."""
        for field in (
            "full_name",
            "matricule",
            "department",
            "email",
            "password",
            "confirm_password",
        ):
            response = self.client.post(
                REGISTER_URL,
                make_registration(**{field: ""}),
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"{field!r} should be required",
            )
            self.assertIn(field, response.data)

        self.assertEqual(User.objects.count(), 0)

    def test_unknown_department_is_rejected(self):
        """The department must be one the backend knows about."""
        response = self.client.post(
            REGISTER_URL,
            make_registration(department="teleportation"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("department", response.data)

    def test_blank_body_is_rejected(self):
        """An empty POST is a ``400``, not a ``500``."""
        response = self.client.post(REGISTER_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pin_resembling_the_e_mail_is_a_400_not_a_500(self):
        """A rejected password policy surfaces as a field error.

        ``create()`` runs Django's ``AUTH_PASSWORD_VALIDATORS``, and
        ``UserAttributeSimilarityValidator`` compares the PIN to the student's
        own e-mail. That validator raises *Django's* ``ValidationError``, which
        DRF does not translate - so before this was caught it escaped as an
        unhandled ``500`` HTML page rather than the ``400`` the frontend
        renders on a field. The e-mail below repeats the PIN's digits so the
        similarity check trips deterministically.
        """
        pin = "49170238"
        response = self.client.post(
            REGISTER_URL,
            make_registration(
                # The PIN repeated in the local part, so the similarity check
                # scores 1.0 against the e-mail and trips every time.
                email="amina.49170238@etu.usthb.dz",
                password=pin,
                confirm_password=pin,
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        # No account may have been written by a rejected attempt.
        self.assertEqual(User.objects.count(), 0)


class LoginTests(APITestCase):
    """``POST /api/auth/login``."""

    def setUp(self):
        """Register a valid student once for the whole class."""
        response = self.client.post(
            REGISTER_URL, VALID_REGISTRATION, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        # Start from an anonymous cookie jar for every test.
        self.client.credentials()

    def test_valid_login_starts_a_session(self):
        """Correct credentials return the profile and set the cookie."""
        response = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("sessionid", self.client.cookies)
        self.assertEqual(response.data["user"]["email"], VALID_EMAIL)
        self.assertEqual(response.data["user"]["matricule"], "202331045678")

    def test_login_response_has_no_password_material(self):
        """No PIN and no hash may appear in the login payload."""
        response = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )

        body = response.content.decode()

        self.assertNotIn("49170238", body)
        self.assertNotIn("password", response.data["user"])
        self.assertNotIn("pbkdf2", body)

    def test_wrong_password_is_rejected(self):
        """A wrong PIN is a ``401`` with a generic message."""
        response = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "00000000"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("sessionid", self.client.cookies)

    def test_unknown_email_is_rejected(self):
        """An unregistered address is indistinguishable from a wrong PIN."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "nobody@etu.usthb.dz", "password": "49170238"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_password_and_unknown_email_return_the_same_message(self):
        """The endpoint must not leak which of the two inputs was wrong."""
        wrong_pin = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "00000000"},
            format="json",
        )
        wrong_email = self.client.post(
            LOGIN_URL,
            {"email": "someone.else@etu.usthb.dz", "password": "49170238"},
            format="json",
        )

        self.assertEqual(wrong_pin.data["detail"], wrong_email.data["detail"])

    def test_non_university_domain_is_rejected_before_authentication(self):
        """The domain rule applies on login too, not only on signup."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "amina@gmail.com", "password": "49170238"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_password_is_rejected(self):
        """A blank PIN is a ``400``, not an authentication attempt."""
        response = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SessionLifecycleTests(APITestCase):
    """``/api/auth/me`` and ``/api/auth/logout``."""

    def setUp(self):
        """Register and log in a valid student."""
        self.client.post(REGISTER_URL, VALID_REGISTRATION, format="json")

    def test_me_requires_authentication(self):
        """An anonymous caller gets ``401``."""
        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_the_current_user_only(self):
        """A signed-in student sees their own record and nobody else's."""
        self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )

        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], VALID_EMAIL)
        self.assertEqual(response.data["user"]["full_name"], "Amina Benali")
        self.assertEqual(response.data["user"]["department"], "computer_science")

    def test_me_never_returns_password_material(self):
        """The profile endpoint must not expose credentials."""
        self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )

        response = self.client.get(ME_URL)

        self.assertNotIn("password", response.data["user"])
        self.assertNotIn("pbkdf2", response.content.decode())

    def test_logout_ends_the_session(self):
        """After logout the same cookie no longer authenticates anything."""
        self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)

        logout = self.client.post(LOGOUT_URL, {}, format="json")
        self.assertEqual(logout.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(ME_URL).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_login_rotates_the_session_key(self):
        """Session fixation defence: the pre-login id must not survive login."""
        anonymous = self.client.get(ME_URL)
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
        before = self.client.cookies.get("sessionid")

        self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )
        after = self.client.cookies.get("sessionid")

        if before is not None:
            self.assertNotEqual(before.value, after.value)
        self.assertIsNotNone(after)


class CsrfTests(APITestCase):
    """Mutating endpoints reject requests without the CSRF token.

    Uses ``enforce_csrf_checks`` so the assertion is real: DRF's test client
    otherwise authenticates around CSRF and would hide the bug this guards.
    """

    def setUp(self):
        """Use a client that does *not* bypass CSRF, and register a student."""
        from rest_framework.test import APIClient

        self.client = APIClient(enforce_csrf_checks=True)
        self.client.credentials()

    def test_csrf_endpoint_sets_the_cookie(self):
        """``GET /api/auth/csrf/`` seeds the token the browser echoes back."""
        response = self.client.get(CSRF_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("csrftoken", self.client.cookies)

    def _csrf_headers(self):
        """Return the headers a browser would send after visiting the seed."""
        self.client.get(CSRF_URL)
        token = self.client.cookies["csrftoken"].value
        return {"HTTP_X_CSRFTOKEN": token}

    def test_register_without_token_is_forbidden(self):
        """A cross-site form post cannot register an account."""
        response = self.client.post(
            REGISTER_URL, VALID_REGISTRATION, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(User.objects.count(), 0)

    def test_register_with_token_succeeds(self):
        """With the cookie + header pair, registration works as normal."""
        response = self.client.post(
            REGISTER_URL,
            VALID_REGISTRATION,
            format="json",
            **self._csrf_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_login_without_token_is_forbidden(self):
        """Login is CSRF-protected too - otherwise a page could log a student
        into an account the attacker chose."""
        self.client.post(
            REGISTER_URL,
            VALID_REGISTRATION,
            format="json",
            **self._csrf_headers(),
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": VALID_EMAIL, "password": "49170238"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
