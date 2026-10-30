"""Serializers for the RAG chatbot API.

Only *input* is serialised here. Output is deliberately plain dictionaries
built in :mod:`chatbot.views`, because the payloads mix three sources (the
``ChatSession``/``ChatMessage`` rows, the retrieval citations, and the
localisation ``kind`` flag) and a ``ModelSerializer`` would fight that shape
rather than describe it.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import ChatMessage, ChatSession

__all__ = [
    "ChatMessageSerializer",
    "ChatSessionSerializer",
    "MessageCreateSerializer",
    "SessionCreateSerializer",
]

#: A question is a question, not a document upload. 4000 characters is roughly
#: six screens of text - far beyond any legitimate exam question, and a
#: sensible ceiling before the embedding stage does any work.
MAX_QUESTION_LENGTH = 4000


class MessageCreateSerializer(serializers.Serializer):
    """Validates a newly asked question."""

    content = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=MAX_QUESTION_LENGTH,
        error_messages={
            "required": "A question is required.",
            "blank": "A question is required.",
            "max_length": (
                f"Your question must be at most {MAX_QUESTION_LENGTH} "
                "characters."
            ),
        },
    )


class SessionCreateSerializer(serializers.Serializer):
    """Validates an optional title for a brand-new conversation.

    Notes:
        ``title`` is optional on purpose: the UI creates a conversation *before*
        the first question is typed, so requiring a name would force the
        student to invent one. When it is omitted, the first question becomes
        the title (see :meth:`chatbot.views.ChatSessionViewSet.perform_create`
        and the title promotion in the message view).
    """

    title = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=255,
    )


class ChatMessageSerializer(serializers.ModelSerializer):
    """Read-only projection of one transcript entry.

    ``context_chunks`` and ``sources`` are returned as-is: they are the
    provenance record, and reshaping them here would mean the API and the
    database could drift apart unnoticed.
    """

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "role",
            "content",
            "context_chunks",
            "sources",
            "created_at",
        ]
        read_only_fields = fields


class ChatSessionSerializer(serializers.ModelSerializer):
    """Read-only projection of one conversation in the sidebar.

    ``message_count`` is annotated by the list view, so the sidebar can show
    how long a thread is without fetching every message.
    """

    message_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ChatSession
        fields = [
            "id",
            "title",
            "message_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
