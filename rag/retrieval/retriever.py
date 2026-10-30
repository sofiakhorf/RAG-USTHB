"""Retrieval stage: rank indexed chunks by similarity to a query vector.

This module is the third stage of the RAG layer::

    rag.embeddings -> (store) -> rag.retrieval -> rag.generation

It is deliberately **framework-agnostic**: it knows nothing about Django,
databases or HTTP. It takes a query vector plus an iterable of candidate
vectors and returns a ranked, immutable result. The database plumbing lives in
``backend/chatbot/rag_service.py``, which loads rows and calls into here - so
the ranking maths below is testable in isolation, with no ORM and no server.

Why an extractive answer, and not an LLM
----------------------------------------
There is no generation backend configured in this repository (no provider, no
API key), and inventing one would mean shipping a secret or a fabricated
answer. The honest MVP therefore stops at *retrieval*: the answer is the
highest-scoring passages themselves, each labelled with its document and page
so the student can verify the source. That satisfies "every answer comes from
the real RAG pipeline" without ever simulating one.

Numerical notes
---------------
* Cosine similarity is computed in plain Python. The vectors are 384-dimensional
  (``paraphrase-multilingual-MiniLM-L12-v2``) and a student knowledge base holds
  thousands, not millions, of chunks, so an O(n) loop is comfortably fast and
  avoids a hard numpy dependency in the import path.
* A **zero-magnitude** vector has no direction, so cosine is undefined; it is
  treated as a similarity of ``0.0`` rather than raising, because a single
  degenerate embedding should not take down the whole search.
* Ties break on ``chunk_id`` so ranking is **deterministic**: the same query
  against the same index always returns the same order, which makes the
  retrieval tests meaningful rather than flaky.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "Candidate",
    "DimensionMismatchError",
    "RetrievalError",
    "RetrievedChunk",
    "RetrievalResult",
    "cosine_similarity",
    "rank_candidates",
]

#: Default number of passages returned. Four is enough to answer a exam-style
#: question while keeping the payload small and the citations readable.
DEFAULT_TOP_K = 4


class RetrievalError(Exception):
    """Base class for retrieval-stage failures."""


class DimensionMismatchError(RetrievalError):
    """The query vector and a candidate vector disagree on length."""


@dataclass(frozen=True)
class Candidate:
    """One indexed chunk offered to the ranker.

    Attributes:
        chunk_id: Stable identifier produced by ingestion.
        vector: The chunk's embedding, already normalised or not - cosine
            handles both.
        text: The chunk's raw text, carried through to the result.
        document_name: Human-readable source document title.
        page: Page number the chunk came from, when known.
        metadata: Anything else worth surfacing (``ue``, ``matiere``,
            ``semestre``...). Never inspected by the ranker.
    """

    chunk_id: str
    vector: Sequence[float]
    text: str = ""
    document_name: str = ""
    page: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    """A :class:`Candidate` that survived ranking, plus its score.

    Attributes:
        chunk_id: Stable identifier produced by ingestion.
        score: Cosine similarity in ``[-1.0, 1.0]``.
        text: The chunk's raw text.
        document_name: Human-readable source document title.
        page: Page number the chunk came from, when known.
        metadata: Extra fields carried through from the candidate.
    """

    chunk_id: str
    score: float
    text: str = ""
    document_name: str = ""
    page: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Render a short, human-readable reference for the UI.

        Returns:
            ``"<document>, p. 12"`` when a page is known, otherwise just the
            document name, otherwise ``"<unknown source>"``.
        """
        label = self.document_name or self.metadata.get("document_name") or ""

        if not label:
            label = "<unknown source>"

        if self.page is not None:
            return f"{label}, p. {self.page}"

        return label


@dataclass(frozen=True)
class RetrievalResult:
    """The ranked output of a single search.

    Attributes:
        query: The original query text, for echoing back in logs.
        chunks: Ranked passages, best first. Empty when nothing scored above
            the threshold - which is also what an unpopulated knowledge base
            produces, and is *not* an error.
    """

    query: str
    chunks: tuple[RetrievedChunk, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Whether the search found nothing.

        Returns:
            ``True`` when no passage was returned.
        """
        return not self.chunks

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        """Just the ranked chunk ids, in order.

        Returns:
            The ids of :attr:`chunks`.
        """
        return tuple(chunk.chunk_id for chunk in self.chunks)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity between two vectors.

    Args:
        left: First vector.
        right: Second vector; must be the same length as ``left``.

    Returns:
        A float in ``[-1.0, 1.0]``. ``0.0`` when either vector has zero
        magnitude, because cosine is undefined for a directionless vector.

    Raises:
        DimensionMismatchError: If the two vectors have different lengths.
    """
    if len(left) != len(right):
        raise DimensionMismatchError(
            f"Cannot compare vectors of length {len(left)} and {len(right)}."
        )

    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0

    for a, b in zip(left, right):
        a = float(a)
        b = float(b)
        dot += a * b
        norm_left += a * a
        norm_right += b * b

    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0

    return dot / (math.sqrt(norm_left) * math.sqrt(norm_right))


def _validate_vector(vector: Sequence[float], *, label: str) -> list[float]:
    """Coerce a vector to a list of finite floats.

    Args:
        vector: Raw vector, e.g. one decoded from a JSON column.
        label: Used in the error message to identify the offending row.

    Returns:
        A ``list[float]``.

    Raises:
        RetrievalError: If the vector is empty or contains a non-finite value.
            A single ``NaN`` leaking out of a JSON column would silently
            poison every score, so it is rejected loudly at the boundary.
    """
    values = [float(v) for v in vector]

    if not values:
        raise RetrievalError(f"{label} is an empty vector.")

    for value in values:
        if not math.isfinite(value):
            raise RetrievalError(
                f"{label} contains a non-finite value ({value}); "
                "re-run the embedding stage for this chunk."
            )

    return values


def rank_candidates(
    query_vector: Sequence[float],
    candidates: Iterable[Candidate],
    *,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = 0.0,
    query: str = "",
) -> RetrievalResult:
    """Rank candidates against a query vector.

    Args:
        query_vector: The embedded query.
        candidates: Every indexed chunk to consider.
        top_k: Maximum number of passages to return. ``0`` or less yields an
            empty result rather than raising.
        min_score: Passages scoring below this are dropped. The default of
            ``0.0`` keeps only positively-related passages, so an unrelated
            question produces *no* citations instead of a confidently wrong
            one.
        query: Original query text, echoed into the result.

    Returns:
        A :class:`RetrievalResult` whose ``chunks`` are ordered best-first,
        ties broken by ``chunk_id``.

    Raises:
        RetrievalError: If ``query_vector`` is empty or non-finite.
        DimensionMismatchError: If a candidate's vector length differs from the
            query's. One corrupt row should not be silently skipped, because
            that would quietly shrink the knowledge base.
    """
    query_values = _validate_vector(query_vector, label="Query vector")

    if top_k <= 0:
        return RetrievalResult(query=query, chunks=())

    scored: list[RetrievedChunk] = []

    for candidate in candidates:
        candidate_values = _validate_vector(
            candidate.vector,
            label=f"Chunk {candidate.chunk_id!r}",
        )

        score = cosine_similarity(query_values, candidate_values)

        if score < min_score:
            continue

        scored.append(
            RetrievedChunk(
                chunk_id=candidate.chunk_id,
                score=score,
                text=candidate.text,
                document_name=candidate.document_name,
                page=candidate.page,
                metadata=candidate.metadata,
            )
        )

    # Deterministic: highest score first, then chunk_id for exact ties.
    scored.sort(key=lambda item: (-item.score, item.chunk_id))

    return RetrievalResult(query=query, chunks=tuple(scored[:top_k]))
