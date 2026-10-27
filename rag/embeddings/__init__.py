"""Embeddings stage: chunk text -> normalized multilingual vectors.

Public surface::

    from rag.embeddings import EmbeddingError, embed_chunks, load_embedding_model

The stage reads the pipeline's ``chunks_output.jsonl`` through
:mod:`rag.ingestion` and returns in-memory records. It does **not** persist
anything - vector storage belongs to a later stage.

Two deliberate choices:

* **Lazy attribute access.** ``rag/__init__``-level imports would otherwise
  pull in :mod:`rag.embeddings.encoder` before ``python -m
  rag.embeddings.encoder`` executes it, which runpy flags with a
  "found in sys.modules" warning and which imports the module twice. Deferring
  via module ``__getattr__`` (PEP 562) keeps both ``from rag.embeddings import
  embed_chunks`` and ``-m`` running exactly one copy.
* **No heavy ML import at package import time.** ``sentence_transformers``
  and torch are only imported when a model is actually loaded.
"""

from __future__ import annotations

import importlib
from typing import Any

# Public name -> submodule that defines it.
_EXPORTS = {
    "CHUNKS_FILE": "encoder",
    "MODEL_DIMENSION": "encoder",
    "MODEL_NAME": "encoder",
    "EmbeddingError": "encoder",
    "chunk_id_for": "encoder",
    "create_embeddings": "encoder",
    "embed_chunks": "encoder",
    "load_embedding_model": "encoder",
    "validate_embeddings": "encoder",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public names on first use (PEP 562)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
