"""
Embeddings-stage tests - RAG-USTHB.
====================================
STATUS:   NEW FILE. No production file is modified by running it.

SCOPE:    rag/embeddings/encoder.py - input handling, model lifecycle,
          chunk/vector association, id stability, vector validation and the
          typed error surface.

NO NETWORK: the model is always a local stub (FakeModel) or an injected mock.
            `load_embedding_model` is patched, so neither torch weights nor
            huggingface.co are ever touched.

RUN:      .venv\\Scripts\\python.exe rag\\tests\\test_embeddings.py
"""

import hashlib
import json
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from core.models import Chunk, ChunkMetadata  # EXISTING project model (read-only import)
from rag.ingestion import ChunkLoadError, make_chunk_id  # existing ingestion helpers
from rag.embeddings.encoder import (  # noqa: E402
    EmbeddingError,
    chunk_id_for,
    create_embeddings,
    embed_chunks,
    load_embedding_model,
    validate_embeddings,
)


# ======================================================================
# Deterministic stand-in for SentenceTransformer
# ======================================================================
def deterministic_vector(text: str, dim: int) -> list[float]:
    """Stable unit-length vector derived from the text (no randomness)."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [
        (seed[i % len(seed)] / 255.0) - 0.5 for i in range(dim)
    ]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


class FakeModel:
    """Records how it was called; returns deterministic normalized vectors."""

    def __init__(self, dim: int = 8, fail: bool = False):
        self.dim = dim
        self.fail = fail
        self.calls: list[dict] = []

    def encode(self, texts, batch_size=32, normalize_embeddings=True,
               convert_to_numpy=True, show_progress_bar=False):
        self.calls.append(
            {
                "texts": list(texts),
                "batch_size": batch_size,
                "normalize_embeddings": normalize_embeddings,
            }
        )
        if self.fail:
            raise RuntimeError("simulated encoder failure")
        return [deterministic_vector(t, self.dim) for t in texts]


class TestModelLifecycle(unittest.TestCase):
    """The model must be loaded once per run, never once per chunk."""

    def test_model_loaded_exactly_once_for_many_chunks(self):
        model = FakeModel()
        with mock.patch(
            "rag.embeddings.encoder.load_embedding_model",
            return_value=model,
        ) as loader:
            with tempfile.TemporaryDirectory() as tmp:
                path = write_jsonl(tmp, [make_chunk(f"doc {i}") for i in range(6)])
                results = embed_chunks(chunks_file=path)

        self.assertEqual(len(results), 6)
        self.assertEqual(loader.call_count, 1)  # once, not six times

    def test_encode_receives_all_texts_with_normalization(self):
        model = FakeModel(dim=8)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, [make_chunk("alpha"), make_chunk("beta")])
            embed_chunks(chunks_file=path, model=model, batch_size=4)

        self.assertEqual(len(model.calls), 1)
        call = model.calls[0]
        self.assertEqual(len(call["texts"]), 2)
        self.assertEqual(call["batch_size"], 4)
        self.assertTrue(call["normalize_embeddings"])  # normalized embeddings

    def test_injected_model_skips_the_loader_entirely(self):
        with mock.patch(
            "rag.embeddings.encoder.load_embedding_model"
        ) as loader:
            with tempfile.TemporaryDirectory() as tmp:
                path = write_jsonl(tmp, [make_chunk("x")])
                embed_chunks(chunks_file=path, model=FakeModel())
        loader.assert_not_called()

    def test_create_embeddings_short_circuits_on_empty_input(self):
        model = FakeModel()
        self.assertEqual(create_embeddings([], model), [])
        self.assertEqual(model.calls, [])  # encode never invoked


# ======================================================================
# Input handling
# ======================================================================
class TestInputHandling(unittest.TestCase):

    def test_missing_input_file_raises_file_not_found(self):
        missing = Path(tempfile.gettempdir()) / "definitely_missing_chunks.jsonl"
        if missing.exists():
            missing.unlink()
        with self.assertRaises(FileNotFoundError) as ctx:
            embed_chunks(chunks_file=missing)
        self.assertIn(str(missing), str(ctx.exception))

    def test_empty_input_file_returns_empty_without_loading_model(self):
        with mock.patch(
            "rag.embeddings.encoder.load_embedding_model"
        ) as loader:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "empty.jsonl"
                path.write_text("", encoding="utf-8")
                results = embed_chunks(chunks_file=path)
        self.assertEqual(results, [])
        loader.assert_not_called()  # no pointless model download

    def test_blank_lines_only_file_is_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.jsonl"
            path.write_text("\n\n   \n", encoding="utf-8")
            self.assertEqual(embed_chunks(chunks_file=path, model=FakeModel()), [])

    def test_invalid_record_still_rejected_by_ingestion_contract(self):
        """The embeddings stage must not weaken existing loader semantics."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"text": "no metadata at all"}) + "\n")
            with self.assertRaises(ChunkLoadError):
                embed_chunks(chunks_file=path, model=FakeModel())

    def test_input_file_is_never_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, [make_chunk("lecture 1"), make_chunk("lecture 2")])
            before = path.read_bytes()
            embed_chunks(chunks_file=path, model=FakeModel())
            self.assertEqual(path.read_bytes(), before)


# ======================================================================
# Chunk <-> vector association and id stability
# ======================================================================
class TestAssociationAndIds(unittest.TestCase):

    def test_one_chunk_produces_one_well_formed_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, [make_chunk("planning des examens session 1")])
            results = embed_chunks(chunks_file=path, model=FakeModel(dim=8))

        self.assertEqual(len(results), 1)
        rec = results[0]
        self.assertEqual(set(rec), {"index", "chunk_id", "text", "metadata", "embedding"})
        self.assertEqual(rec["index"], 0)
        self.assertEqual(rec["text"], "planning des examens session 1")
        self.assertEqual(rec["metadata"]["document_name"], "doc-0.pdf")
        self.assertEqual(len(rec["embedding"]), 8)

    def test_many_chunks_keep_their_order_and_pairing(self):
        texts = ["texte alpha", "texte beta", "texte gamma", "texte delta"]
        chunks = [make_chunk(t, index=i) for i, t in enumerate(texts)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, chunks)
            results = embed_chunks(chunks_file=path, model=FakeModel(dim=8))

        self.assertEqual([r["index"] for r in results], [0, 1, 2, 3])
        self.assertEqual([r["text"] for r in results], texts)
        # each embedding is the vector that belongs to ITS OWN text
        for rec in results:
            self.assertEqual(
                rec["embedding"], deterministic_vector(rec["text"], 8),
                "vector does not belong to the text it was paired with",
            )

    def test_metadata_is_preserved_verbatim(self):
        chunk = make_chunk("contenu", page=7, sheet_name="Inscrits",
                           block_range="4-10", is_fallback=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, [chunk])
            rec = embed_chunks(chunks_file=path, model=FakeModel(dim=8))[0]

        self.assertEqual(rec["metadata"], chunk.metadata.model_dump(mode="json"))
        self.assertEqual(rec["metadata"]["page"], 7)
        self.assertEqual(rec["metadata"]["sheet_name"], "Inscrits")
        self.assertTrue(rec["metadata"]["is_fallback"])

    def test_chunk_ids_match_the_existing_helper(self):
        chunks = [make_chunk(f"doc {i}") for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, chunks)
            results = embed_chunks(chunks_file=path, model=FakeModel(dim=8))

        expected = [make_chunk_id(c) for c in chunks]
        self.assertEqual([r["chunk_id"] for r in results], expected)

    def test_chunk_ids_are_stable_across_runs(self):
        chunks = [make_chunk("contenu stable", page=3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, chunks)
            first = embed_chunks(chunks_file=path, model=FakeModel(dim=8))
            second = embed_chunks(chunks_file=path, model=FakeModel(dim=8))
        self.assertEqual(first[0]["chunk_id"], second[0]["chunk_id"])

    def test_chunk_ids_are_unique_for_distinct_chunks(self):
        chunks = [make_chunk(f"contenu {i}", index=i) for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, chunks)
            ids = [r["chunk_id"] for r in
                   embed_chunks(chunks_file=path, model=FakeModel(dim=8))]
        self.assertEqual(len(set(ids)), len(ids))

    def test_chunk_id_prefers_an_existing_id_field(self):
        """If the model ever grows an `id`, it wins - no new scheme invented."""
        class WithId:
            id = "already-assigned-123"
            text = "x"
            metadata = ChunkMetadata(document_name="d.pdf", family_type="A")

        self.assertEqual(chunk_id_for(WithId()), "already-assigned-123")

    def test_chunk_id_falls_back_for_plain_chunk(self):
        chunk = make_chunk("simple")
        self.assertFalse(hasattr(chunk, "id"))  # documents today's schema
        self.assertEqual(chunk_id_for(chunk), make_chunk_id(chunk))


# ======================================================================
# Vector validation
# ======================================================================
class TestVectorValidation(unittest.TestCase):

    def test_consistent_finite_vectors_pass_and_report_dimension(self):
        vectors = [deterministic_vector("a", 8), deterministic_vector("b", 8)]
        self.assertEqual(validate_embeddings(vectors, [1, 2]), 8)

    def test_count_mismatch_is_rejected(self):
        with self.assertRaises(EmbeddingError) as ctx:
            validate_embeddings([deterministic_vector("a", 8)], [1, 2])
        self.assertIn("mismatch", str(ctx.exception))

    def test_empty_vector_list_is_rejected(self):
        with self.assertRaises(EmbeddingError):
            validate_embeddings([], [1])

    def test_zero_length_vector_is_rejected(self):
        with self.assertRaises(EmbeddingError):
            validate_embeddings([[]], [1])

    def test_inconsistent_dimensions_are_rejected(self):
        with self.assertRaises(EmbeddingError) as ctx:
            validate_embeddings(
                [deterministic_vector("a", 8), deterministic_vector("b", 6)],
                [1, 2],
            )
        self.assertIn("dimension", str(ctx.exception))

    def test_non_finite_values_are_rejected(self):
        good = deterministic_vector("a", 8)
        for bad_value in (float("nan"), float("inf"), float("-inf")):
            broken = list(good)
            broken[3] = bad_value
            with self.assertRaises(EmbeddingError) as ctx:
                validate_embeddings([broken], [1])
            self.assertIn("non-finite", str(ctx.exception))

    def test_embedded_records_have_finite_normalized_vectors(self):
        chunks = [make_chunk("alpha"), make_chunk("beta"), make_chunk("gamma")]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(tmp, chunks)
            results = embed_chunks(chunks_file=path, model=FakeModel(dim=8))

        dims = {len(r["embedding"]) for r in results}
        self.assertEqual(dims, {8})
        for rec in results:
            for v in rec["embedding"]:
                self.assertTrue(math.isfinite(v))
            norm = math.sqrt(sum(v * v for v in rec["embedding"]))
            self.assertAlmostEqual(norm, 1.0, places=6)  # normalized


# ======================================================================
# Error surface
# ======================================================================
class TestErrorSurface(unittest.TestCase):

    def test_model_load_failure_is_wrapped_as_embedding_error(self):
        with mock.patch(
            "rag.embeddings.encoder.load_embedding_model",
            side_effect=EmbeddingError("weights unavailable"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = write_jsonl(tmp, [make_chunk("x")])
                with self.assertRaises(EmbeddingError) as ctx:
                    embed_chunks(chunks_file=path)
        self.assertEqual(ctx.exception.code, "embedding_error")

    def test_encoding_failure_is_wrapped_as_embedding_error(self):
        with self.assertRaises(EmbeddingError) as ctx:
            create_embeddings(["a", "b"], FakeModel(fail=True))
        self.assertIn("Encoding failed", str(ctx.exception))
        self.assertEqual(ctx.exception.code, "embedding_error")

    def test_embedding_error_is_a_rag_error(self):
        from rag.ingestion import RagError
        self.assertTrue(issubclass(EmbeddingError, RagError))

    def test_model_load_failure_reports_model_name_clearly(self):
        """A failing constructor must surface as a readable EmbeddingError.

        `sentence_transformers` is replaced in sys.modules so neither the
        weights nor the network are touched.
        """
        exploding = types.SimpleNamespace(
            SentenceTransformer=mock.Mock(
                side_effect=RuntimeError("simulated load failure")
            )
        )
        with mock.patch.dict(sys.modules, {"sentence_transformers": exploding}):
            with self.assertRaises(EmbeddingError) as ctx:
                load_embedding_model(model_name="some/model-name")

        message = str(ctx.exception)
        self.assertIn("some/model-name", message)   # names what failed
        self.assertIn("simulated load failure", message)  # keeps the cause

    def test_missing_sentence_transformers_is_reported_as_embedding_error(self):
        """A broken native dependency must not escape as a raw ImportError."""
        with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            with self.assertRaises(EmbeddingError) as ctx:
                load_embedding_model()
        self.assertIn("could not be imported", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ImportError)


# ======================================================================
# Helpers
# ======================================================================
def make_chunk(text: str, index: int = 0, **meta) -> Chunk:
    base = dict(
        document_name=f"doc-{index}.pdf",
        family_type="A",
    )
    base.update(meta)
    return Chunk(text=text, metadata=ChunkMetadata(**base))


def write_jsonl(directory: str, chunks) -> Path:
    path = Path(directory) / "chunks_output.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")
    return path


if __name__ == "__main__":
    unittest.main(verbosity=2)
