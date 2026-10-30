"""Retrieval boundary: rank indexed chunks against a query vector.

Public surface::

    from rag.retrieval import (
        Candidate,
        RetrievalResult,
        RetrievedChunk,
        cosine_similarity,
        rank_candidates,
    )

The module depends only on the standard library. It does not import Django,
the ORM or any embedding model, so the ranking maths can be exercised
standalone (see ``rag/tests/test_rag_contract.py``) and the database plumbing
stays where it belongs - in ``backend/chatbot/rag_service.py``.
"""

from __future__ import annotations

from .retriever import (
    DEFAULT_TOP_K,
    Candidate,
    DimensionMismatchError,
    RetrievalError,
    RetrievalResult,
    RetrievedChunk,
    cosine_similarity,
    rank_candidates,
)

__all__ = [
    "DEFAULT_TOP_K",
    "Candidate",
    "DimensionMismatchError",
    "RetrievalError",
    "RetrievalResult",
    "RetrievedChunk",
    "cosine_similarity",
    "rank_candidates",
]
