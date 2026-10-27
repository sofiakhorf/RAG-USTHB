"""Ingestion boundary: turn pipeline JSONL exports into validated RAG input.

Public surface::

    from rag.ingestion import ChunkLoadError, load_chunks_jsonl, make_chunk_id

The module depends only on the standard library and on ``core.models`` - i.e.
on what the pipeline already requires. It deliberately does **not** import
``pipeline/`` or ``parsers/``, so reading and validating an export never drags
in OCR, Scrapy or the batch machinery.
"""

from __future__ import annotations

from .loader import (
    VALID_FAMILIES,
    ChunkLoadError,
    RagError,
    load_chunks_jsonl,
    make_chunk_id,
    validate_chunk_semantics,
)

__all__ = [
    "VALID_FAMILIES",
    "ChunkLoadError",
    "RagError",
    "load_chunks_jsonl",
    "make_chunk_id",
    "validate_chunk_semantics",
]
