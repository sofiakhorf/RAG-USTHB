"""Generation stage: retrieved passages -> a grounded LLM answer.

Sits after :mod:`rag.retrieval` in the pipeline the retriever has always
documented::

    rag.embeddings -> rag.retrieval -> rag.generation

Talks to any OpenAI-compatible ``/chat/completions`` endpoint. Configuration is
read from the environment (``LLM_API_KEY`` / ``LLM_PROVIDER`` / ``LLM_MODEL`` /
``LLM_BASE_URL``); when none is present, :func:`is_configured` reports ``False``
and the caller serves the extractive answer instead. Nothing here invents text.
"""

from __future__ import annotations

from rag.generation.provider import (
    DEFAULTS,
    GenerationError,
    GenerationUnavailable,
    LLMConfig,
    build_prompt,
    generate,
    is_configured,
    load_config,
)

__all__ = [
    "DEFAULTS",
    "GenerationError",
    "GenerationUnavailable",
    "LLMConfig",
    "build_prompt",
    "generate",
    "is_configured",
    "load_config",
]
