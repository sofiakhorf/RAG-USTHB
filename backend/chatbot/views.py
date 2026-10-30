"""Conversation + question/answer endpoints.

Isolation
---------
Every queryset in this module is filtered by ``request.user`` *before* the
object is resolved, and :meth:`ModelViewSet.get_object` then looks the
requested id up inside that filtered set. The consequence is the security
property the specification demands: a student who edits the UUID in the URL, or
replays another student's API call, gets a **404** - not a 403, which would
confirm the conversation exists, and certainly not the messages.

The filter lives in :meth:`ChatSessionViewSet.get_queryset` and nowhere else,
so there is exactly one place to audit.

CSRF
----
No explicit ``csrf_protect`` is needed here (unlike ``users.views``): every
endpoint requires authentication, and DRF's ``SessionAuthentication``
automatically enforces CSRF for any request that resolves to a real user.
"""

from __future__ import annotations

from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from chatbot import rag_service
from chatbot.models import ChatMessage, ChatSession
from chatbot.serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    MessageCreateSerializer,
    SessionCreateSerializer,
)

__all__ = ["ChatSessionViewSet"]

#: ``ChatSession.title`` ships with this default. It is used as the sentinel
#: that means "this conversation has no real name yet", so the first question
#: can be promoted into the sidebar label.
DEFAULT_SESSION_TITLE = "New conversation"


class ChatSessionViewSet(ModelViewSet):
    """CRUD for a student's own conversations, plus the ask-an-answer action.

    ``GET``/``POST``/``DELETE`` operate on the collection and on a single
    conversation; ``POST /api/chat/sessions/<id>/messages/`` asks a question
    and returns the RAG answer together with its citations.
    """

    http_method_names = ["get", "post", "delete", "head", "options"]
    serializer_class = ChatSessionSerializer
    permission_classes = [IsAuthenticated]

    # DRF's default lookup regex is ``[^/.]+``, which would happily accept a
    # non-UUID and turn a typo into a 500 from the ORM. Constraining it means
    # malformed ids are a clean 404 before any query runs.
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    # ------------------------------------------------------------------
    # Scoping - the single source of the isolation guarantee.
    # ------------------------------------------------------------------

    def get_queryset(self):
        """Return only the signed-in student's conversations.

        Returns:
            Conversations owned by ``request.user``, most recently active
            first, with ``message_count`` annotated so the sidebar does not
            need to fetch every transcript. Anonymous callers get an empty
            queryset; :class:`~rest_framework.permissions.IsAuthenticated`
            rejects them before any of it is used.
        """
        user = self.request.user

        if user is None or not user.is_authenticated:
            return ChatSession.objects.none()

        return (
            ChatSession.objects.filter(user=user)
            .annotate(message_count=Count("messages"))
            .order_by("-updated_at")
        )

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def create(self, request, *args, **kwargs):
        """Start a new, empty conversation.

        Args:
            request: The incoming request. ``title`` is optional.

        Returns:
            ``201`` with the new conversation. It belongs to ``request.user``
            unconditionally - a ``user`` field in the body is ignored, so a
            student cannot create a conversation on someone else's behalf.
        """
        serializer = SessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        title = serializer.validated_data.get("title") or DEFAULT_SESSION_TITLE

        session = ChatSession.objects.create(user=request.user, title=title)

        payload = ChatSessionSerializer(session).data

        return Response(payload, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        """Fetch one conversation together with its transcript.

        Args:
            request: The incoming request.
            kwargs: ``pk`` - the conversation's UUID.

        Returns:
            ``200`` with ``{"session": ..., "messages": [...]}``.

        Raises:
            ``404``: If no conversation with that id belongs to the caller.
        """
        session = self.get_object()

        return Response(
            {
                "session": ChatSessionSerializer(session).data,
                "messages": ChatMessageSerializer(
                    session.messages.all(), many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------------
    # Asking a question
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="messages")
    def ask(self, request, pk=None):
        """Ask one question and answer it from the indexed documents.

        ``POST /api/chat/sessions/<uuid>/messages/``

        Args:
            request: The incoming request; ``content`` holds the question.
            kwargs: ``pk`` - the conversation's UUID.

        Returns:
            ``200`` on success::

                {
                  "kind": "extractive" | "no_evidence",
                  "answer": "<body>",
                  "sources": [{"document", "page", "excerpt", "score", ...}],
                  "question_message": {...},
                  "answer_message": {...},
                }

            ``kind`` is what the frontend localises; ``answer`` is the English
            fallback. ``no_evidence`` is a **successful** retrieval that found
            nothing - it is not an error, and its ``sources`` list is empty.

        Raises:
            ``404``: The conversation does not exist *for this user*.
            ``400``: The question is missing or too long.
            ``503``: The embedding model is unavailable; ``500``: the retrieval
                stage failed. In both cases the question is still saved (it was
                really asked) and its id is returned so the transcript stays
                consistent when the page reloads.
        """
        session = self.get_object()  # ownership-filtered; 404 otherwise

        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        question = serializer.validated_data["content"]

        # The question really was asked, so it is persisted before the answer
        # is attempted - a failure downstream must not erase the student's
        # input.
        question_message = ChatMessage.objects.create(
            session=session,
            role="user",
            content=question,
        )

        # An untitled conversation takes its name from the first question, so
        # the sidebar is never a column of identical "New conversation" rows.
        if session.title == DEFAULT_SESSION_TITLE:
            session.title = question[:255]

        try:
            result = rag_service.answer_question(question)
        except rag_service.EmbeddingModelUnavailable as exc:
            session.save()  # keep the title promotion
            return Response(
                {
                    "detail": str(exc),
                    "error": "rag_unavailable",
                    "message_id": str(question_message.id),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except rag_service.RagServiceError as exc:
            session.save()
            return Response(
                {
                    "detail": str(exc),
                    "error": "rag_failed",
                    "message_id": str(question_message.id),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        answer_message = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=result.text,
            # Chunk.id UUIDs, so provenance survives in the database
            # independently of the JSON `sources` blob.
            context_chunks=result.chunk_ids,
            sources=result.sources,
        )

        # Bumps `updated_at` (auto_now), which is what puts this conversation
        # at the top of the sidebar.
        session.save()

        return Response(
            {
                "kind": result.kind,
                "answer": result.text,
                "sources": result.sources,
                "question_message": ChatMessageSerializer(question_message).data,
                "answer_message": ChatMessageSerializer(answer_message).data,
            },
            status=status.HTTP_200_OK,
        )
