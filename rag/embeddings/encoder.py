"""Embeddings stage: turn validated chunks into normalized vectors.

This module is the second stage of the RAG layer::

    pipeline -> chunks_output.jsonl -> rag.ingestion -> rag.embeddings -> (future: store)

It deliberately stops at an in-memory list of records. Nothing here writes to
a vector database, and nothing here re-reads or rewrites the preprocessing
output - the JSONL export is opened read-only via
:func:`rag.ingestion.load_chunks_jsonl`.

Design notes
------------
* **The model is imported lazily**, inside :func:`load_embedding_model`.
  Importing this module therefore stays cheap: unit tests can mock the model
  and never pay the ~2s torch import, and a broken native dependency surfaces
  as a typed :class:`EmbeddingError` with an actionable message instead of a
  traceback at import time.
* **The model is loaded once per :func:`embed_chunks` call**, never once per
  chunk. Reloading per chunk would re-read the weights from disk for every
  record.
* **Vector order is the input order.** ``model.encode`` already guarantees
  this; :func:`validate_embeddings` asserts the count still matches afterwards
  so a silent truncation cannot pass.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Sequence

from rag.ingestion import RagError, load_chunks_jsonl, make_chunk_id

__all__ = [
    "MODEL_NAME",
    "CHUNKS_FILE",
    "EmbeddingError",
    "create_embeddings",
    "embed_chunks",
    "load_embedding_model",
    "main",
    "validate_embeddings",
]

# Multilingual embedding model: French, Arabic and English share one space,
# which is what USTHB documents (and mixed-language queries) require.
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Default input = the file produced by `main.py` (pipeline CLI).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHUNKS_FILE = PROJECT_ROOT / "chunks_output.jsonl"

#: Embedding dimensionality of MODEL_NAME. Recorded so an incompatible vector
#: width is caught immediately rather than at query time inside the store.
MODEL_DIMENSION = 384


class EmbeddingError(RagError):
    """The embedding stage could not load a model or encode its input."""

    code = "embedding_error"


def load_embedding_model(model_name: str = MODEL_NAME):
    """Load the SentenceTransformer model exactly once.

    The heavy import happens here rather than at module scope so that
    ``import rag.embeddings.encoder`` stays cheap and side-effect free.

    Args:
        model_name: Hugging Face model id, or a local path to a cached copy.

    Returns:
        A ``SentenceTransformer`` instance ready to encode.

    Raises:
        EmbeddingError: If ``sentence_transformers`` cannot be imported, or
            the weights cannot be fetched (no network / empty HF cache /
            native dependency failure). The message names the model so the
            operator knows exactly what failed to load.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # ImportError, but DLL/OSError also reach here
        raise EmbeddingError(
            "sentence_transformers could not be imported. The native "
            "dependencies (torch / numpy / scipy) are likely built for a "
            "different Python version than this interpreter. "
            f"Original error: {exc}"
        ) from exc

    try:
        return SentenceTransformer(model_name)
    except Exception as exc:
        raise EmbeddingError(
            f"Could not load embedding model {model_name!r}. Check network "
            "access to huggingface.co, or point MODEL_NAME at a local cached "
            f"copy. Original error: {type(exc).__name__}: {exc}"
        ) from exc


def create_embeddings(
    texts: Sequence[str],
    model: Any,
    batch_size: int = 32,
    show_progress_bar: bool = False,
) -> list[list[float]]:
    """Encode texts into normalized vectors, in batches, in input order.

    Args:
        texts: Chunk texts. May be empty, in which case no call is made.
        model: A ``SentenceTransformer`` (or any object with ``encode``).
        batch_size: Chunks sent to the model per forward pass. Batching is
            done by the model itself - the model is *not* reloaded per batch.
        show_progress_bar: Opt-in tqdm bar; off by default so logs and tests
            stay readable.

    Returns:
        One list of floats per input text, same length and order.

    Raises:
        EmbeddingError: If ``model.encode`` fails.
    """
    if not texts:
        return []

    try:
        vectors = model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
        )
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(
            f"Encoding failed for {len(texts)} text(s): "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # `encode` may return a numpy array or a list depending on the backend.
    if hasattr(vectors, "tolist"):
        vectors = vectors.tolist()

    return [list(vector) for vector in vectors]


def chunk_id_for(chunk: Any) -> str:
    """Return a stable id for ``chunk`` without inventing a new scheme.

    Preference order:

    1. An ``id`` field, if the chunk model ever grows one (it does **not**
       today - ``core.models.Chunk`` has only ``text`` and ``metadata``).
    2. Otherwise the existing
       :func:`rag.ingestion.loader.make_chunk_id` helper, which hashes
       document name, family, locator and text.

    Args:
        chunk: A :class:`core.models.Chunk`.

    Returns:
        A stable string id.

    Raises:
        EmbeddingError: If neither an id field nor a usable chunk is available.
    """
    existing_id = getattr(chunk, "id", None)
    if existing_id:
        return str(existing_id)

    try:
        return make_chunk_id(chunk)
    except Exception as exc:
        raise EmbeddingError(
            f"Could not derive a chunk id: {type(exc).__name__}: {exc}"
        ) from exc


def validate_embeddings(
    vectors: Sequence[Sequence[float]],
    chunks: Sequence[Any],
) -> int:
    """Assert the vectors are a faithful, well-formed mirror of the chunks.

    Checks, in order:

    1. Count - exactly one vector per chunk, so no document silently loses
       representation.
    2. Non-emptiness - a zero-length vector has no retrievable meaning.
    3. Dimension consistency - one width for the whole batch; a mixed width
       means two different models wrote into the same batch.
    4. Finiteness - NaN/Inf poison cosine similarity for *every* neighbour.

    Args:
        vectors: Encoded vectors.
        chunks: The chunks they were produced from.

    Returns:
        The shared vector dimension, so callers can record it.

    Raises:
        EmbeddingError: On the first violation, with the offending position.
    """
    if len(vectors) != len(chunks):
        raise EmbeddingError(
            f"vector/chunk count mismatch: {len(vectors)} vectors for "
            f"{len(chunks)} chunks"
        )
    if not vectors:
        raise EmbeddingError("no vectors were produced")

    dimension = len(vectors[0])
    if dimension == 0:
        raise EmbeddingError("vector 0 is empty")

    for position, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise EmbeddingError(
                f"vector {position} has dimension {len(vector)}, "
                f"expected {dimension}"
            )
        for value in vector:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EmbeddingError(
                    f"vector {position} contains a non-finite value: {value!r}"
                )

    return dimension


def embed_chunks(
    chunks_file: Path = CHUNKS_FILE,
    batch_size: int = 32,
    model: Any = None,
    show_progress_bar: bool = False,
) -> list[dict]:
    """Load, validate and embed every chunk while preserving its metadata.

    The input file is only read; it is never rewritten.

    Args:
        chunks_file: JSONL export produced by the preprocessing pipeline.
        batch_size: Chunks per forward pass.
        model: Optional pre-loaded model. When omitted the model is loaded
            once, here. Tests inject a mock through this parameter.
        show_progress_bar: Opt-in encoding progress bar.

    Returns:
        One dict per chunk::

            {"index": int, "chunk_id": str, "text": str,
             "metadata": dict, "embedding": list[float]}

        ``index`` is the 0-based position in the input file. It is a
        *positional link*, not an identifier - ``chunk_id`` remains the id.

    Raises:
        FileNotFoundError: If ``chunks_file`` does not exist.
        EmbeddingError: If the file cannot be parsed, the model fails to load,
            encoding fails, or the vectors fail validation.
        ChunkLoadError: If a record violates the ingestion contract.
    """
    chunks_file = Path(chunks_file)

    if not chunks_file.is_file():
        raise FileNotFoundError(f"Chunks file not found: {chunks_file}")

    # 1. Load and validate against the ingestion contract (read-only).
    chunks = load_chunks_jsonl(str(chunks_file))

    # 2. Empty input is a valid no-op: no model download, no work.
    if not chunks:
        return []

    # 3. Load the model exactly once for the whole batch of chunks.
    if model is None:
        model = load_embedding_model()

    # 4. Encode every chunk text in batches, keeping input order.
    vectors = create_embeddings(
        texts=[chunk.text for chunk in chunks],
        model=model,
        batch_size=batch_size,
        show_progress_bar=show_progress_bar,
    )

    # 5. Fail loudly before pairing anything up.
    validate_embeddings(vectors, chunks)

    # 6. Keep each vector tied to its original chunk, text and metadata.
    return [
        {
            "index": index,
            "chunk_id": chunk_id_for(chunk),
            "text": chunk.text,
            "metadata": chunk.metadata.model_dump(mode="json"),
            "embedding": vector,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]


def main() -> int:
    """CLI entry point. Prints a summary; writes nothing to disk."""
    parser = argparse.ArgumentParser(
        description="Generate embeddings from a chunks_output.jsonl export."
    )
    parser.add_argument(
        "--chunks-file",
        type=Path,
        default=CHUNKS_FILE,
        help="Input JSONL produced by the preprocessing pipeline",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Chunks encoded per forward pass",
    )
    args = parser.parse_args()

    print(f"Loading chunks from {args.chunks_file} ...")
    try:
        embedded = embed_chunks(
            chunks_file=args.chunks_file,
            batch_size=args.batch_size,
            show_progress_bar=True,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    except RagError as exc:
        print(f"ERROR [{exc.code}]: {exc}")
        return 1

    if not embedded:
        print("No chunks found - nothing to embed.")
        return 0

    dimension = len(embedded[0]["embedding"])
    print("\nEmbedding stage completed.")
    print(f"  Embedded chunks : {len(embedded)}")
    print(f"  Vector dimension: {dimension}")
    print(f"  Model           : {MODEL_NAME}")
    print(f"  First chunk id  : {embedded[0]['chunk_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
