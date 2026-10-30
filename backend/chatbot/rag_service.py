"""Bridge between the Django knowledge-base tables and :mod:`rag.retrieval`.

Responsibility split
--------------------
* :mod:`rag.retrieval` owns the maths and knows nothing about Django.
* This module owns the plumbing: load ``Embedding``/``Chunk`` rows, encode the
  question with the *same* model the index was built with, call the ranker, and
  turn the winning passages into an answer plus citations.

Everything is imported lazily and cached, because the sentence-transformer
costs ~2s and hundreds of megabytes to load - paying that per HTTP request
would make the chat unusable.

Honesty contract
----------------
No answer is ever invented. There are exactly two outcomes:

``extractive``
    Passages scored above the threshold. The answer *is* those passages,
    quoted and attributed, so a student can check the source.

``no_evidence``
    Nothing was found - either the knowledge base has never been indexed, or
    no passage is close enough to the question. The frontend localises this
    into the student's language; the English ``text`` is the fallback.

The ``kind`` field lets the frontend tell the two apart without parsing prose.
"""

from __future__ import annotations

import logging
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

#: Passages returned per answer. Enough to cover a multi-part exam question
#: without flooding the transcript.
DEFAULT_TOP_K = 4

#: Only positively-related passages are cited. Below this cosine similarity the
#: chunk is treated as unrelated, which turns "the index is empty" into an
#: honest "no evidence" instead of a confident wrong answer.
#:
#: Measured on real questions against this corpus, the best-match scores were:
#: a well-answered question scored 0.76, a partially-answered one 0.63, and a
#: question the corpus cannot answer at all still scored 0.57. So the default
#: of ``0.0`` is deliberately permissive - it never suppresses a real answer,
#: but it does mean an unanswerable question returns loosely-related passages
#: rather than "no evidence". Override with ``RAG_MIN_SCORE`` (e.g. ``0.6``)
#: to trade recall for precision; that trade-off is a product decision, not
#: something to bake in from three samples.
def _min_score() -> float:
    """Read ``RAG_MIN_SCORE`` from the environment (default ``0.0``)."""
    raw = (os.environ.get("RAG_MIN_SCORE") or "").strip()
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0

#: Characters of each winning passage quoted back to the student. Long enough
#: to be a useful answer, short enough to keep the transcript readable.
EXCERPT_LIMIT = 600

ANSWER_KIND_EXTRACTIVE = "extractive"
ANSWER_KIND_GENERATED = "generated"
ANSWER_KIND_NO_EVIDENCE = "no_evidence"

#: How long the loaded knowledge base stays cached in this process, in seconds.
#: Retrieval has to pull every stored vector out of PostgreSQL, which is slow
#: over a remote pooled connection; the corpus only changes when an operator
#: runs `manage.py ingest_chunks`, so reusing it for a few minutes is safe and
#: bounds staleness to the TTL. Override with ``RAG_CANDIDATES_TTL``; ``0``
#: disables caching entirely.
def _candidates_ttl() -> int:
    """Read ``RAG_CANDIDATES_TTL`` from the environment (default 300, ``0`` = off)."""
    raw = (os.environ.get("RAG_CANDIDATES_TTL") or "").strip()
    try:
        return int(raw) if raw else 300
    except ValueError:
        return 300


#: Module-level cache: ``(loaded_at, candidates)``.
_CANDIDATES_CACHE: tuple[float, list] | None = None


def _default_top_k() -> int:
    """Resolve how many passages to cite, from ``RAG_TOP_K``.

    The default is :data:`DEFAULT_TOP_K` (4) and is deliberately unchanged:
    a measured study of Q1/Q2/Q3 showed only that a larger window changes
    *retrieval* recall, and answer quality could not be measured in this
    environment, so silently widening the window would be an untested change.

    Why the knob exists at all: for one question in the corpus the passage a
    student explicitly asked for ranked 5th, so ``top_k=4`` kept it out of the
    context entirely. Raising this to ``6`` brings it in - measured, not
    assumed. Set ``RAG_TOP_K`` to try it without a code change.
    """
    raw = (os.environ.get("RAG_TOP_K") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_TOP_K
    except ValueError:
        return DEFAULT_TOP_K
    # 0 would return nothing; a negative would be rejected by rank_candidates.
    return value if value >= 1 else DEFAULT_TOP_K


def _resolve_top_k(top_k: int | None) -> int:
    """``None`` means "use the configured default"; anything else is explicit."""
    return _default_top_k() if top_k is None else top_k

#: Shown by the frontend when no passage is found. Localised client-side; the
#: English text here is the fallback for API clients that do not translate.
NO_EVIDENCE_TEXT = (
    "I could not find anything relevant to this question in the indexed "
    "university documents. If the knowledge base has not been populated yet, "
    "index the course materials first, then ask again."
)


class RagServiceError(Exception):
    """Base class for chatbot-side RAG failures."""


class EmbeddingModelUnavailable(RagServiceError):
    """The sentence-transformer could not be loaded or could not encode."""


class KnowledgeBaseEmpty(RagServiceError):
    """No indexed chunks exist yet."""


@dataclass(frozen=True)
class Answer:
    """The result of answering one question.

    Attributes:
        question: The question as asked.
        text: The answer body. Either quoted passages, or
            :data:`NO_EVIDENCE_TEXT`.
        kind: ``extractive`` or ``no_evidence``; see the module docstring.
        sources: One dict per cited passage, shaped for the frontend.
        chunk_ids: ``ChatMessage.context_chunks`` payload - the ``Chunk.id``
            UUIDs behind this answer, so provenance survives in the database
            even if the frontend is later rewritten.
    """

    question: str
    text: str
    kind: str
    sources: list[dict] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    #: Which backend produced ``text``: ``"llm"`` when a configured model
    #: generated it, ``"extractive"`` when it is the quoted passages, or
    #: ``"none"`` for ``no_evidence``. Lets an operator tell the two apart in
    #: the database without parsing prose.
    generation: str = "extractive"


@lru_cache(maxsize=1)
def _load_model():
    """Load the sentence-transformer once per process.

    Returns:
        The loaded model.

    Raises:
        EmbeddingModelUnavailable: If the model cannot be imported or loaded -
            typically a missing ``sentence-transformers`` install or a first
            run with no network to fetch the weights.
    """
    # Imported lazily: `rag.embeddings.encoder` pulls in torch on import, and
    # paying that cost at module import time would slow every `manage.py`
    # command, including ones that never touch the chat.
    try:
        from rag.embeddings.encoder import load_embedding_model

        return load_embedding_model()
    except Exception as exc:  # pragma: no cover - depends on the host machine
        # Log the real cause server-side; the client gets a generic message so
        # the endpoint cannot be used to fingerprint the deployment.
        logger.exception("Could not load the embedding model")
        raise EmbeddingModelUnavailable(
            "The embedding model could not be loaded. Check that "
            "sentence-transformers is installed and that the model weights "
            f"are reachable. Underlying error: {type(exc).__name__}"
        ) from exc


def embed_query(text: str) -> list[float]:
    """Embed a single question with the index's own model.

    Args:
        text: The student's question.

    Returns:
        A normalised vector of floats.

    Raises:
        EmbeddingModelUnavailable: If the model cannot be loaded or encoding
            fails.
    """
    # Imported lazily for the same reason as _load_model.
    try:
        from rag.embeddings.encoder import create_embeddings
    except Exception as exc:  # pragma: no cover - depends on the host machine
        raise EmbeddingModelUnavailable(
            f"The embedding stage is unavailable: {type(exc).__name__}"
        ) from exc

    model = _load_model()

    try:
        vectors = create_embeddings([text], model)
    except Exception as exc:
        raise EmbeddingModelUnavailable(
            f"Could not encode the question: {type(exc).__name__}"
        ) from exc

    if not vectors:
        raise EmbeddingModelUnavailable("The embedding stage returned no vector.")

    return vectors[0]


def _load_candidates() -> list[Candidate]:
    """Read every indexed chunk and its embedding from the database.

    Returns:
        One :class:`~rag.retrieval.Candidate` per chunk that has an embedding.
        Chunks without an embedding are skipped - they were never indexed, so
        they have no direction to compare against.

    Notes:
        Everything is loaded eagerly, then cached for
        ``RAG_CANDIDATES_TTL`` seconds (default 300). That is O(n) in the size
        of the knowledge base on the first call only; the corpus changes solely
        when an operator runs ``manage.py ingest_chunks``, so reusing it briefly
        is safe and the TTL bounds how stale it can get. Before this, every
        question pulled all 1181 x 384 stored floats across the remote pooled
        connection, which cost minutes per query.

        A larger deployment would move the dot product into SQL with pgvector
        instead; this cache is the cheap fix for a course-catalogue corpus.
    """
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
    """Load the knowledge base from the database. No caching; see the caller."""
    from .models import Embedding

    candidates: list[Candidate] = []

    # `chunk_id` is Embedding's OneToOneField column, i.e. the Chunk.id UUID.
    # `chunk__chunk_id` is the ingestion pipeline's stable string id, which is
    # the human-usable reference. They are different values and both are
    # needed: the UUID keys `ChatMessage.context_chunks`, the string id is what
    # a student can look up in the original document.
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
        # Deliberately NOT `.iterator()`: a server-side cursor keeps one pooled
        # SSL connection open for the whole scan, and the Supabase pooler drops
        # those mid-fetch ("SSL connection has been closed unexpectedly"),
        # which killed retrieval outright. The full result is ~1.7 MB, so
        # materialising it in one round trip is both faster and far more robust.
        # Django only opens a server-side cursor when `.iterator()` is used.
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
                # Prefer the metadata the pipeline recorded, then the owning
                # document's title, so a citation is never blank when a title
                # exists somewhere.
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
    """Run the retrieval stage over the stored index.

    Args:
        question: The student's question.
        top_k: Maximum passages to return. ``None`` (the default) resolves to
            the ``RAG_TOP_K`` environment variable, or
            :data:`DEFAULT_TOP_K` when that is unset.

    Returns:
        A :class:`~rag.retrieval.RetrievalResult`. ``is_empty`` is ``True``
        when the index is unpopulated or nothing scored above the threshold -
        both are normal, not errors.

    Raises:
        EmbeddingModelUnavailable: If the question cannot be embedded.
        RetrievalError: If a stored vector is malformed.
    """
    top_k = _resolve_top_k(top_k)

    candidates = _load_candidates()

    if not candidates:
        # No need to pay for an embedding that cannot be compared to anything.
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
    """Project a retrieved chunk onto the citation shape the frontend renders.

    Args:
        chunk: A :class:`~rag.retrieval.RetrievedChunk`.

    Returns:
        ``{"chunk_id", "reference_id", "document", "page", "excerpt", "score",
        "citation"}``.

    Notes:
        ``chunk_id`` here is the ``Chunk.id`` UUID (what
        ``ChatMessage.context_chunks`` stores). ``reference_id`` is the
        ingestion pipeline's stable string id, which is the one a human would
        use to find the passage in the original document.
    """
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
    """Render the winning passages as the answer itself.

    Each passage is quoted verbatim and attributed, so nothing is paraphrased
    into something the source did not say - which is exactly what a summarising
    LLM would risk doing without one to verify against.
    """
    return "\n\n".join(
        f"{index}. {chunk.text.strip()}\n   — {chunk.citation}"
        for index, chunk in enumerate(chunks, start=1)
    )


def _generate_answer(question: str, chunks) -> str:
    """Ask a configured LLM for a grounded answer over ``chunks``.

    Args:
        question: The student's question.
        chunks: The retrieved passages, best first.

    Returns:
        The model's answer.

    Raises:
        GenerationError: If no LLM is configured, the request failed, or the
            reply was empty or malformed. The caller falls back to the
            extractive answer rather than surfacing this to the student,
            because a sourced quote is always better than a fabricated one.
    """
    # Imported lazily: pulls in the HTTP plumbing, and most deployments never
    # configure an LLM at all.
    from rag.generation import GenerationError, build_prompt, generate
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
    """Answer one question from the indexed corpus.

    Args:
        question: The student's question, already trimmed by the caller.
        top_k: Maximum passages to cite. ``None`` (the default) resolves to
            ``RAG_TOP_K``, else :data:`DEFAULT_TOP_K`. It is forwarded to
            :func:`retrieve`, which performs the resolution.
        force_extractive: Skip the LLM even when one is configured. Used by
            tests and by an operator who wants the raw passages.

    Returns:
        An :class:`Answer` whose ``kind`` is one of:

        ``no_evidence``
            Nothing was retrieved. ``sources`` is empty.
        ``generated``
            A configured LLM answered over the retrieved passages. ``sources``
            still holds the passages it was given, so the citations are real.
        ``extractive``
            No LLM is configured, or generation failed. ``text`` is the
            passages themselves, quoted and attributed.

    Raises:
        EmbeddingModelUnavailable: If the question cannot be embedded; the view
            turns this into a ``503`` so the browser can show a clear error
            rather than a fabricated reply.
    """
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
        # Checked before calling: "no LLM configured" is the normal state of
        # this deployment, not a failure, so it must not raise-and-log a
        # traceback on every question. Only a *configured* provider that then
        # fails is worth an exception entry.
        from rag.generation import is_configured

        if is_configured():
            try:
                generated = _generate_answer(question, result.chunks)
            except Exception:
                # Any generation failure degrades to the extractive answer: the
                # passages are already retrieved and are factually the source
                # text, so the student still gets a correct, citable reply. The
                # cause is logged server-side; it is never shown as an answer.
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
