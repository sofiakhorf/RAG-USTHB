"""Ingestion boundary between the pipeline JSONL export and the RAG stage.

This module is the promoted, importable home of three helpers that were first
written inside ``rag/tests/test_rag_contract.py``:

* :func:`load_chunks_jsonl`       - read + schema-validate a ``chunks_output.jsonl``
* :func:`validate_chunk_semantics` - the rules pydantic cannot express
* :func:`make_chunk_id`           - deterministic, content-addressed chunk identity

Promoting them means production code and the contract tests exercise **one**
implementation. If they had stayed duplicated in the test file, the tests would
have been verifying a private copy rather than the code the pipeline ships.

Why it is shaped this way
-------------------------
* **Validates against the real model.** Records are parsed with
  ``core.models.Chunk.model_validate``, so any schema drift in
  ``core/models.py`` is caught here instead of surfacing later as an
  unfindable vector.
* **Fails loudly with a line number.** A malformed record aborts the load and
  names the offending line, because a silently dropped chunk is invisible
  until a user asks the question it would have answered.
* **No new dependencies.** Only stdlib + the project's existing pydantic,
  both of which the pipeline already requires.

Import example
--------------
    from rag.ingestion.loader import ChunkLoadError, load_chunks_jsonl, make_chunk_id

    try:
        chunks = load_chunks_jsonl("chunks_output.jsonl")
    except ChunkLoadError as exc:
        ...  # report line number to the operator, do not index a partial file
"""

from __future__ import annotations

import hashlib
import json

from core.models import Chunk

__all__ = [
    "VALID_FAMILIES",
    "ChunkLoadError",
    "RagError",
    "load_chunks_jsonl",
    "make_chunk_id",
    "validate_chunk_semantics",
]

# ---------------------------------------------------------------------
# Error types (Phase 7/10 contract)
# ---------------------------------------------------------------------


class RagError(Exception):
    """Base class for every RAG-layer failure; carries a stable machine code."""

    code = "rag_error"


class ChunkLoadError(RagError):
    """A pipeline export could not be read or did not satisfy the contract."""

    code = "chunk_load_error"


#: ``family_type`` values the router in ``pipeline/router.py`` can emit.
#: ``FALLBACK`` is included on purpose: the router does produce it for
#: unrecognised files (see ``pipeline/router.py``), so rejecting it would
#: discard exactly the documents an operator most needs to be told about.
VALID_FAMILIES = {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "EXCEL", "FALLBACK"}


# ---------------------------------------------------------------------
# Phase 4: JSONL loading + validation rules
# ---------------------------------------------------------------------
def load_chunks_jsonl(path: str) -> list[Chunk]:
    """Read pipeline output (``main.py`` JSONL export). Fails loudly on bad lines.

    Every non-blank line must be valid JSON that
    :meth:`core.models.Chunk.model_validate` accepts, and it must then pass
    :func:`validate_chunk_semantics`.

    Args:
        path: Filesystem path to the ``chunks_output.jsonl`` export.

    Returns:
        One :class:`core.models.Chunk` per record, in file order.

    Raises:
        ChunkLoadError: Missing file, invalid JSON, schema violation or a
            semantic violation. The message always carries ``line <n>`` so the
            operator can open the offending record directly.
        OSError: If the path exists but cannot be read (permissions, I/O).

    Note:
        The whole file is all-or-nothing: a failure raises rather than
        returning the records read so far. Indexing a truncated export would
        silently shrink the corpus, which is far worse than stopping.
    """
    records: list[Chunk] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ChunkLoadError(f"line {lineno}: invalid JSON: {exc}") from exc
            try:
                rec = Chunk.model_validate(obj)
            except Exception as exc:
                raise ChunkLoadError(f"line {lineno}: schema violation: {exc}") from exc
            validate_chunk_semantics(rec, lineno)
            records.append(rec)
    return records


def validate_chunk_semantics(rec: "Chunk", lineno: int = 0) -> None:
    """Apply the validation rules that pydantic types alone cannot express.

    Checks, in order:

    1. ``text`` is present and not blank - an empty chunk embeds to noise and
       can never be cited usefully.
    2. ``metadata.document_name`` is present and not blank - provenance. Every
       retrieved chunk must be traceable to a document the user can open.
    3. ``metadata.family_type`` is in :data:`VALID_FAMILIES` - catches router
       regressions and unknown families instead of indexing garbage.
    4. ``metadata.page >= -1`` - ``-1`` is the project's "unknown page"
       sentinel (see ``parsers/family_g.py``); anything below it is a bug.

    Args:
        rec: A validated :class:`core.models.Chunk`.
        lineno: 1-based line number, used only to make the error actionable.

    Raises:
        ChunkLoadError: On the first violation found. The message always
            starts with ``line <n>`` for traceability back to the export.
    """
    if not rec.text or not rec.text.strip():
        raise ChunkLoadError(f"line {lineno}: empty chunk text")
    if not rec.metadata.document_name or not rec.metadata.document_name.strip():
        raise ChunkLoadError(f"line {lineno}: missing document_name (provenance)")
    if rec.metadata.family_type not in VALID_FAMILIES:
        raise ChunkLoadError(
            f"line {lineno}: unknown family_type {rec.metadata.family_type!r}"
        )
    if rec.metadata.page is not None and rec.metadata.page < -1:
        raise ChunkLoadError(f"line {lineno}: page < -1")


def make_chunk_id(rec: "Chunk") -> str:
    """Derive a stable chunk id from document identity, locator and content.

    Payload order (do not reorder without bumping the index)::

        document_name|family_type|sheet_name|block_range|article_number|page|chapter|text

    hashed with SHA-256 and truncated to 32 hex characters.

    Properties this buys us:

    * **Deterministic** - re-running the pipeline on unchanged input yields the
      same ids, so re-indexing overwrites rows instead of duplicating them.
    * **Content-sensitive** - editing the text, or moving the chunk within its
      document, changes the id, so stale vectors are replaced rather than kept.
    * **Locator-aware** - sheet/page/article/chapter participate, so two
      identical boilerplate paragraphs from different locations do not collide.

    Args:
        rec: A validated :class:`core.models.Chunk`.

    Returns:
        A 32-character lowercase hex string suitable as a primary key in the
        vector store.
    """
    m = rec.metadata
    locator = "|".join(
        str(x) for x in [m.sheet_name, m.block_range, m.article_number, m.page, m.chapter]
    )
    payload = f"{m.document_name}|{m.family_type}|{locator}|{rec.text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
