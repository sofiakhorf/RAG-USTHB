"""RAG system prompt and context construction.

The instruction block lives in :mod:`rag.prompts.system`, deliberately free of
any provider or network dependency so it can be reviewed and tested on its own.
"""

from __future__ import annotations

from rag.prompts.system import (
    ANSWER_INSTRUCTION,
    RAG_SYSTEM_PROMPT,
    build_context,
    build_messages,
)

__all__ = [
    "ANSWER_INSTRUCTION",
    "RAG_SYSTEM_PROMPT",
    "build_context",
    "build_messages",
]
