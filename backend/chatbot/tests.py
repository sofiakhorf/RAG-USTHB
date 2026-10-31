"""Tests for the conversation + RAG question/answer API.

Run with::

    .venv\\Scripts\\python.exe manage.py test --settings=config.test_settings

The most important class here is :class:`OwnershipIsolationTests`. Requirement 6
of the specification is a hard security requirement - *"one user must never be
able to access another user's conversations"* - so it is tested from every angle
an attacker could reach: reading, listing, writing a message, and deleting.

The RAG stage itself is replaced with a stub in the view tests. That is
deliberate: loading a sentence-transformer would make the suite depend on a
multi-hundred-megabyte download, and these tests are about the HTTP contract
and the database writes, not about embedding quality. The retrieval *maths* is
tested separately in ``rag/tests/test_retrieval.py``.
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from chatbot.models import ChatMessage, ChatSession
from chatbot.rag_service import (
    ANSWER_KIND_EXTRACTIVE,
    ANSWER_KIND_NO_EVIDENCE,
    Answer,
    EmbeddingModelUnavailable,
)
from chatbot.views import DEFAULT_SESSION_TITLE

User = get_user_model()

SESSIONS_URL = "/api/chat/sessions/"

ANSWER_BODY = (
    "1. Le cours porte sur la normalisation des bases de donnees.\n"
    "   -- SI S6, p. 4"
)
SOURCES = [
    {
        "chunk_id": "11111111-1111-1111-1111-111111111111",
        "reference_id": "abc123",
        "document": "Syllabus SI S6",
        "page": 4,
        "excerpt": "Le cours porte sur la normalisation...",
        "score": 0.8123,
        "citation": "Syllabus SI S6, p. 4",
    }
]


def stub_answer(kind=ANSWER_KIND_EXTRACTIVE, text=ANSWER_BODY, sources=SOURCES):
    """Build a real :class:`Answer` without touching the embedding model."""
    return Answer(
        question="q",
        text=text,
        kind=kind,
        sources=sources if kind == ANSWER_KIND_EXTRACTIVE else [],
        chunk_ids=[source["chunk_id"] for source in (sources or [])],
    )


def make_user(email: str, matricule: str):
    """Create a student directly, bypassing the HTTP layer."""
    local_part = email.split("@", 1)[0]
    user = User.objects.create_user(
        username=email,
        email=email,
        password="49170238",
        first_name=local_part.replace(".", " ").title(),
    )
    from chatbot.models import StudentProfile

    StudentProfile.objects.create(
        user=user,
        matricule=matricule,
        department="computer_science",
        role="student",
    )
    return user


class ConversationCrudTests(APITestCase):
    """List / create / retrieve / delete for one's own conversations."""

    def setUp(self):
        """Sign in a student."""
        self.user = make_user("amina.benali@etu.usthb.dz", "202331045678")
        self.client.force_login(self.user)

    def test_requires_authentication(self):
        """Anonymous callers are rejected before any queryset runs."""
        self.client.logout()

        for method, url in (
            ("get", SESSIONS_URL),
            ("post", SESSIONS_URL),
            ("get", f"{SESSIONS_URL}11111111-1111-1111-1111-111111111111/"),
        ):
            response = getattr(self.client, method)(url, {}, format="json")

            self.assertIn(
                response.status_code,
                (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                f"{method.upper()} {url} should be protected",
            )

    def test_create_assigns_the_current_user(self):
        """A new conversation always belongs to whoever asked for it."""
        response = self.client.post(SESSIONS_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], DEFAULT_SESSION_TITLE)

        session = ChatSession.objects.get(pk=response.data["id"])
        self.assertEqual(session.user, self.user)

    def test_create_ignores_a_user_field_in_the_body(self):
        """A student cannot open a conversation on someone else's behalf."""
        victim = make_user("yacine.hamdi@etu.usthb.dz", "202399999999")

        response = self.client.post(
            SESSIONS_URL, {"user": str(victim.pk)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = ChatSession.objects.get(pk=response.data["id"])
        self.assertEqual(session.user, self.user)
        self.assertNotEqual(session.user, victim)

    def test_create_accepts_an_explicit_title(self):
        """A title given up-front is stored verbatim."""
        response = self.client.post(
            SESSIONS_URL, {"title": "Normalisation"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Normalisation")

    def test_list_shows_only_your_own_conversations(self):
        """The sidebar must never contain a stranger's thread."""
        mine = ChatSession.objects.create(user=self.user, title="Mine")
        ChatSession.objects.create(
            user=make_user("yacine.hamdi@etu.usthb.dz", "202399999999"),
            title="Not mine",
        )

        response = self.client.get(SESSIONS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["title"] for item in response.data], ["Mine"])
        self.assertNotIn("Not mine", str(response.data))
        self.assertEqual(mine.user, self.user)

    def test_list_annotates_message_count(self):
        """The sidebar can show thread length without fetching the transcript."""
        session = ChatSession.objects.create(user=self.user, title="Counted")
        ChatMessage.objects.create(session=session, role="user", content="a")
        ChatMessage.objects.create(session=session, role="assistant", content="b")

        response = self.client.get(SESSIONS_URL)

        self.assertEqual(response.data[0]["message_count"], 2)

    def test_retrieve_returns_the_transcript_in_order(self):
        """Opening a conversation restores its messages, oldest first."""
        session = ChatSession.objects.create(user=self.user, title="Thread")
        ChatMessage.objects.create(session=session, role="user", content="Q1")
        ChatMessage.objects.create(session=session, role="assistant", content="A1")
        ChatMessage.objects.create(session=session, role="user", content="Q2")

        response = self.client.get(f"{SESSIONS_URL}{session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session"]["title"], "Thread")
        self.assertEqual(
            [message["content"] for message in response.data["messages"]],
            ["Q1", "A1", "Q2"],
        )

    def test_retrieve_is_idempotent_across_logins(self):
        """A conversation survives logout and logging back in."""
        session = ChatSession.objects.create(user=self.user, title="Persisted")
        ChatMessage.objects.create(session=session, role="user", content="Q1")

        self.client.logout()
        self.client.force_login(self.user)

        response = self.client.get(f"{SESSIONS_URL}{session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["messages"]), 1)

    def test_delete_removes_the_conversation(self):
        """Deleting a conversation removes it and its messages."""
        session = ChatSession.objects.create(user=self.user, title="Doomed")
        ChatMessage.objects.create(session=session, role="user", content="Q1")

        response = self.client.delete(f"{SESSIONS_URL}{session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ChatSession.objects.filter(pk=session.pk).exists())
        self.assertFalse(ChatMessage.objects.filter(session=session).exists())

    def test_malformed_uuid_is_a_clean_404(self):
        """A typo must not become a 500 from the ORM."""
        response = self.client.get(f"{SESSIONS_URL}not-a-uuid/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OwnershipIsolationTests(APITestCase):
    """No student may reach another student's conversation.

    This is the security requirement the specification calls out as critical,
    so it is asserted on every verb that could leak or mutate data.
    """

    def setUp(self):
        """Two students, each with one conversation containing one message."""
        self.alice = make_user("amina.benali@etu.usthb.dz", "202331045678")
        self.bob = make_user("yacine.hamdi@etu.usthb.dz", "202399999999")

        self.alice_session = ChatSession.objects.create(
            user=self.alice, title="Alice secret"
        )
        ChatMessage.objects.create(
            session=self.alice_session,
            role="user",
            content="What is Alice's question?",
        )
        ChatMessage.objects.create(
            session=self.alice_session,
            role="assistant",
            content="Alice's answer.",
        )

    def test_bob_cannot_read_alices_conversation(self):
        """Guessing the UUID yields 404, never the messages."""
        self.client.force_login(self.bob)

        response = self.client.get(f"{SESSIONS_URL}{self.alice_session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn("Alice", response.content.decode())

    def test_bob_cannot_see_alices_conversation_in_the_list(self):
        """The listing is scoped, so nothing leaks there either."""
        self.client.force_login(self.bob)

        response = self.client.get(SESSIONS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        self.assertNotIn("Alice secret", response.content.decode())

    def test_bob_cannot_post_into_alices_conversation(self):
        """Writing into someone else's thread is refused - and nothing is saved."""
        self.client.force_login(self.bob)

        before = ChatMessage.objects.count()

        response = self.client.post(
            f"{SESSIONS_URL}{self.alice_session.pk}/messages/",
            {"content": "Bob was here"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ChatMessage.objects.count(), before)
        self.assertFalse(
            ChatMessage.objects.filter(content="Bob was here").exists()
        )

    def test_bob_cannot_delete_alices_conversation(self):
        """Deleting someone else's thread is refused."""
        self.client.force_login(self.bob)

        response = self.client.delete(f"{SESSIONS_URL}{self.alice_session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(ChatSession.objects.filter(pk=self.alice_session.pk).exists())
        self.assertEqual(ChatMessage.objects.filter(session=self.alice_session).count(), 2)

    def test_404_does_not_distinguish_missing_from_foreign(self):
        """A stranger's id and a random id must look identical.

        Otherwise the endpoint becomes an oracle for enumerating valid
        conversation UUIDs.
        """
        self.client.force_login(self.bob)

        foreign = self.client.get(f"{SESSIONS_URL}{self.alice_session.pk}/")
        nonexistent = self.client.get(
            f"{SESSIONS_URL}99999999-9999-9999-9999-999999999999/"
        )

        self.assertEqual(foreign.status_code, nonexistent.status_code)
        self.assertEqual(foreign.content, nonexistent.content)

    def test_alice_can_still_read_hers_own(self):
        """The isolation filter is not over-broad."""
        self.client.force_login(self.alice)

        response = self.client.get(f"{SESSIONS_URL}{self.alice_session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["messages"]), 2)


class AskQuestionTests(APITestCase):
    """``POST /api/chat/sessions/<id>/messages/``."""

    def setUp(self):
        """Sign in a student with one conversation."""
        self.user = make_user("amina.benali@etu.usthb.dz", "202331045678")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Thread")

    def url(self):
        return f"{SESSIONS_URL}{self.session.pk}/messages/"

    def test_answer_is_saved_with_its_sources(self):
        """Both messages are persisted, and the citations travel with them."""
        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            return_value=stub_answer(),
        ) as stub:
            response = self.client.post(
                self.url(),
                {"content": "What is normalization?"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stub.assert_called_once_with("What is normalization?")

        self.assertEqual(response.data["kind"], ANSWER_KIND_EXTRACTIVE)
        self.assertEqual(response.data["answer"], ANSWER_BODY)
        self.assertEqual(response.data["sources"], SOURCES)

        messages = ChatMessage.objects.filter(session=self.session)
        self.assertEqual(messages.count(), 2)

        question = messages.get(role="user")
        answer = messages.get(role="assistant")
        self.assertEqual(question.content, "What is normalization?")
        self.assertEqual(answer.content, ANSWER_BODY)
        self.assertEqual(answer.sources, SOURCES)
        # Provenance is stored as Chunk.id UUIDs, independently of the JSON
        # `sources` blob.
        self.assertEqual(answer.context_chunks, [SOURCES[0]["chunk_id"]])

    def test_untitled_conversation_adopts_the_first_question(self):
        """The sidebar should not fill up with identical default names."""
        self.session.title = DEFAULT_SESSION_TITLE
        self.session.save()

        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            return_value=stub_answer(),
        ):
            self.client.post(self.url(), {"content": "Explain BCNF"}, format="json")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Explain BCNF")

    def test_a_named_conversation_keeps_its_name(self):
        """An explicit title is never overwritten by a later question."""
        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            return_value=stub_answer(),
        ):
            self.client.post(self.url(), {"content": "Explain BCNF"}, format="json")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Thread")

    def test_question_moves_the_conversation_to_the_top(self):
        """Asking bumps `updated_at`, which is the sidebar's sort key."""
        older = ChatSession.objects.create(user=self.user, title="Older")
        ChatSession.objects.filter(pk=older.pk).update(
            # auto_now would fight an explicit write, so poke the column
            # directly for the fixture.
            updated_at="2020-01-01T00:00:00Z"
        )

        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            return_value=stub_answer(),
        ):
            self.client.post(self.url(), {"content": "Question"}, format="json")

        response = self.client.get(SESSIONS_URL)
        titles = [item["title"] for item in response.data]

        self.assertEqual(titles[0], "Thread")
        self.assertEqual(titles, ["Thread", "Older"])

    def test_no_evidence_is_a_success_not_an_error(self):
        """An empty index answers honestly and still records the exchange."""
        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            return_value=stub_answer(kind=ANSWER_KIND_NO_EVIDENCE, sources=[]),
        ):
            response = self.client.post(
                self.url(), {"content": "Unknown topic"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["kind"], ANSWER_KIND_NO_EVIDENCE)
        self.assertEqual(response.data["sources"], [])
        self.assertEqual(ChatMessage.objects.filter(session=self.session).count(), 2)

    def test_model_failure_returns_503_and_keeps_the_question(self):
        """A down embedding model must not swallow the student's input."""
        from chatbot.rag_service import EmbeddingModelUnavailable

        with mock.patch(
            "chatbot.views.rag_service.answer_question",
            side_effect=EmbeddingModelUnavailable("model unavailable"),
        ):
            response = self.client.post(
                self.url(), {"content": "Explain BCNF"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["error"], "rag_unavailable")
        # The question was really asked, so it survives the failure.
        question = ChatMessage.objects.get(session=self.session, role="user")
        self.assertEqual(question.content, "Explain BCNF")
        self.assertEqual(
            str(response.data["message_id"]), str(question.id)
        )

    def test_blank_question_is_rejected(self):
        """An empty question is a ``400``, and nothing is persisted."""
        response = self.client.post(self.url(), {"content": "   "}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("content", response.data)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_missing_question_is_rejected(self):
        """Omitting the field is a ``400``."""
        response = self.client.post(self.url(), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_overlong_question_is_rejected(self):
        """A paste-bomb is refused before any embedding work happens."""
        response = self.client.post(
            self.url(), {"content": "x" * 5000}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_conversation_with_no_messages_returns_an_empty_transcript(self):
        """A brand-new conversation opens cleanly."""
        response = self.client.get(f"{SESSIONS_URL}{self.session.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["messages"], [])


class EmbedQueryFailureContractTests(SimpleTestCase):
    """``embed_query`` must type every embedding failure *and* log the cause.

    Regression contract for the production 503: the deployed environment was
    missing ``pydantic``, so the lazy import of ``rag.embeddings.encoder``
    raised ``ModuleNotFoundError``. The client correctly received the typed
    ``EmbeddingModelUnavailable`` (-> HTTP 503), but nothing was written to the
    server logs, which made the root cause invisible from Render's dashboard.
    These tests pin both halves: the typed error for the caller, the original
    exception (type + traceback) for the operator.
    """

    def test_encoder_import_failure_is_typed_and_logged(self):
        """A missing dependency surfaces as 503 material *and* a log record."""
        from chatbot import rag_service

        # ``None`` in sys.modules makes the import raise ModuleNotFoundError,
        # which is exactly what Render did when pydantic was absent.
        with mock.patch.dict("sys.modules", {"rag.embeddings.encoder": None}):
            with mock.patch.object(
                rag_service.logger, "exception"
            ) as log:
                with self.assertRaises(EmbeddingModelUnavailable) as ctx:
                    rag_service.embed_query("Qu'est-ce qu'une vue ?")

        self.assertEqual(
            str(ctx.exception),
            "The embedding stage is unavailable: ModuleNotFoundError",
        )
        log.assert_called_once()
        self.assertIn("embedding stage", log.call_args[0][0])

    def test_encode_failure_is_typed_and_logged(self):
        """A model that explodes while encoding is also logged server-side."""
        from chatbot import rag_service

        exploding = mock.Mock(side_effect=RuntimeError("CUDA out of memory"))

        with mock.patch(
            "rag.embeddings.encoder.create_embeddings", exploding
        ), mock.patch(
            "chatbot.rag_service._load_model", return_value=mock.sentinel.model
        ):
            with mock.patch.object(
                rag_service.logger, "exception"
            ) as log:
                with self.assertRaises(EmbeddingModelUnavailable) as ctx:
                    rag_service.embed_query("Comment s'inscrire ?")

        self.assertEqual(
            str(ctx.exception),
            "Could not encode the question: RuntimeError",
        )
        log.assert_called_once()
        self.assertIn("encode the question", log.call_args[0][0])
