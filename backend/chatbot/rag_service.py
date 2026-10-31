
"""Bridge between Django knowledge-base tables and rag.retrieval.

Query embeddings are generated remotely by the private Hugging Face Space.
Stored document embeddings remain in Supabase and are compared locally.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

from rag.retrieval import (
    Candidate,
    RetrievalError,
    RetrievalResult,
    rank_candidates,
)

__all__ = [
    "DEFAULT_TOP_K",
    "ANSWER_KIND_EXTRACTIVE",
    "ANSWER_KIND_GENERATED",
    "ANSWER_KIND_NO_EVIDENCE",
    "Answer",
    "EmbeddingModelUnavailable",
    "KnowledgeBaseEmpty",
    "RagServiceError",
    "answer_question",
    "retrieve",
]

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 4
EXCERPT_LIMIT = 600

ANSWER_KIND_EXTRACTIVE = "extractive"
ANSWER_KIND_GENERATED = "generated"
ANSWER_KIND_NO_EVIDENCE = "no_evidence"

EMBEDDING_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_DIMENSIONS = 384

NO_EVIDENCE_TEXT = (
    "I could not find anything relevant to this question in the indexed "
    "university documents. If the knowledge base has not been populated yet, "
    "index the course materials first, then ask again."
)


def _min_score() -> float:
    raw = (os.environ.get("RAG_MIN_SCORE") or "").strip()
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def _candidates_ttl() -> int:
    raw = (os.environ.get("RAG_CANDIDATES_TTL") or "").strip()
    try:
        return int(raw) if raw else 300
    except ValueError:
        return 300


_CANDIDATES_CACHE: tuple[float, list[Candidate]] | None = None


def _default_top_k() -> int:
    raw = (os.environ.get("RAG_TOP_K") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_TOP_K
    except ValueError:
        return DEFAULT_TOP_K
    return value if value >= 1 else DEFAULT_TOP_K


def _resolve_top_k(top_k: int | None) -> int:
    return _default_top_k() if top_k is None else top_k


class RagServiceError(Exception):
    """Base class for chatbot-side RAG failures."""


class EmbeddingModelUnavailable(RagServiceError):
    """The remote embedding service could not generate an embedding."""


class KnowledgeBaseEmpty(RagServiceError):
    """No indexed chunks exist yet."""


@dataclass(frozen=True)
class Answer:
    """The result of answering one question."""

    question: str
    text: str
    kind: str
    sources: list[dict] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    generation: str = "extractive"


@lru_cache(maxsize=1)
def _get_embedding_client():
    """Create and cache the Hugging Face Gradio client."""

    try:
        from gradio_client import Client

        token = (os.environ.get("HF_TOKEN") or "").strip()

        if not token:
            raise ValueError("HF_TOKEN is not configured.")

        return Client(
            "salsabilhm/rag-usthb-embeddings",
            hf_token=token,
        )

    except Exception as exc:
        logger.exception("Could not connect to Hugging Face Space")
        raise EmbeddingModelUnavailable(
            "The remote embedding service is unavailable: "
            f"{type(exc).__name__}"
        ) from exc


def embed_query(text: str) -> list[float]:
    """Generate one query embedding using the remote Hugging Face Space."""

    if not isinstance(text, str) or not text.strip():
        raise EmbeddingModelUnavailable("The query text is empty or invalid.")

    client = _get_embedding_client()

    try:
        result = client.predict(
            texts=[text],
            api_name="/embed",
        )

        if not isinstance(result, dict):
            raise ValueError("Unexpected response format from embedding API.")

        returned_model = result.get("model")
        if returned_model != EMBEDDING_MODEL_NAME:
            raise ValueError("The embedding API returned an unexpected model.")

        dimensions = result.get("dimensions")
        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("The embedding API returned unexpected dimensions.")

        embeddings = result.get("embeddings")

        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValueError("The embedding API did not return exactly one vector.")

        vector = embeddings[0]

        if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError("The returned embedding vector has an invalid size.")

        vector = [float(value) for value in vector]

        if not all(math.isfinite(value) for value in vector):
            raise ValueError("The embedding vector contains invalid values.")

        return vector

    except Exception as exc:
        logger.exception("Could not generate remote query embedding")
        raise EmbeddingModelUnavailable(
            "Could not generate the query embedding: "
            f"{type(exc).__name__}"
        ) from exc


def _load_candidates() -> list[Candidate]:
    """Load indexed chunks and their stored embeddings, using a short cache."""

    global _CANDIDATES_CACHE

    ttl = _candidates_ttl()

    if ttl > 0 and _CANDIDATES_CACHE is not None:
        loaded_at, cached = _CANDIDATES_CACHE
        if time.monotonic() - loaded_at < ttl:
            return cached

    candidates = _fetch_candidates()

    if ttl > 0:
        _CANDIDATES_CACHE = (time.monotonic(), candidates)

    return candidates


def _fetch_candidates() -> list[Candidate]:
    """Load the knowledge base from the database."""

    from .models import Embedding

    candidates: list[Candidate] = []

    rows = (
        Embedding.objects.select_related("chunk", "chunk__document")
        .values_list(
            "chunk_id",
            "embedding",
            "chunk__chunk_id",
            "chunk__text",
            "chunk__document_name",
            "chunk__document__title",
            "chunk__page",
            "chunk__metadata",
        )
    )

    for (
        chunk_pk,
        vector,
        reference_id,
        text,
        document_name,
        document_title,
        page,
        metadata,
    ) in rows:
        if not vector:
            continue

        candidates.append(
            Candidate(
                chunk_id=str(chunk_pk),
                vector=vector,
                text=text or "",
                document_name=document_name or document_title or "",
                page=page,
                metadata={
                    **(metadata or {}),
                    "chunk_pk": str(chunk_pk),
                    "reference_id": reference_id or "",
                },
            )
        )

    return candidates


def retrieve(question: str, *, top_k: int | None = None) -> RetrievalResult:
    """Embed a question remotely and rank the stored document embeddings."""

    top_k = _resolve_top_k(top_k)
    candidates = _load_candidates()

    if not candidates:
        return RetrievalResult(query=question, chunks=())

    query_vector = embed_query(question)

    return rank_candidates(
        query_vector,
        candidates,
        top_k=top_k,
        min_score=_min_score(),
        query=question,
    )


def _source_payload(chunk) -> dict:
    """Project a retrieved chunk onto the frontend citation shape."""

    metadata = chunk.metadata or {}

    return {
        "chunk_id": str(metadata.get("chunk_pk", "")),
        "reference_id": str(metadata.get("reference_id", "") or chunk.chunk_id),
        "document": chunk.document_name or metadata.get("document_name", ""),
        "page": chunk.page,
        "excerpt": (chunk.text or "")[:EXCERPT_LIMIT],
        "score": round(chunk.score, 4),
        "citation": chunk.citation,
    }


def _extractive_body(chunks) -> str:
    """Return retrieved passages verbatim, with their citations."""

    return "\n\n".join(
        f"{index}. {chunk.text.strip()}\n   — {chunk.citation}"
        for index, chunk in enumerate(chunks, start=1)
    )


def _generate_answer(question: str, chunks) -> str:
    """Generate a grounded answer using the configured LLM."""

    from rag.generation import build_prompt, generate
    from rag.prompts import build_messages

    messages = build_messages(question, chunks)
    logger.debug("LLM prompt:\n%s", build_prompt(messages))

    return generate(messages)


def answer_question(
    question: str,
    *,
    top_k: int | None = None,
    force_extractive: bool = False,
) -> Answer:
    """Answer a question using retrieved university-document passages."""

    result = retrieve(question, top_k=top_k)

    if result.is_empty:
        return Answer(
            question=question,
            text=NO_EVIDENCE_TEXT,
            kind=ANSWER_KIND_NO_EVIDENCE,
            sources=[],
            chunk_ids=[],
            generation="none",
        )

    sources = [_source_payload(chunk) for chunk in result.chunks]

    if not force_extractive:
        from rag.generation import is_configured

        if is_configured():
            try:
                generated = _generate_answer(question, result.chunks)
            except Exception:
                logger.exception(
                    "LLM generation failed; falling back to the extractive answer"
                )
            else:
                return Answer(
                    question=question,
                    text=generated,
                    kind=ANSWER_KIND_GENERATED,
                    sources=sources,
                    chunk_ids=list(result.chunk_ids),
                    generation="llm",
                )

    return Answer(
        question=question,
        text=_extractive_body(result.chunks),
        kind=ANSWER_KIND_EXTRACTIVE,
        sources=sources,
        chunk_ids=list(result.chunk_ids),
        generation="extractive",
    )
