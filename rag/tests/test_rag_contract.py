"""
PROPOSED RAG DATA-CONTRACT TESTS - RAG-USTHB audit (Phase 8).
=============================================================
STATUS:   NEW FILE - does not exist in the original project. Nothing was modified.
PURPOSE:  Executable specification of the data contract proposed in the audit report
          (Phases 4-7): JSONL ingestion validation, stable chunk IDs, idempotent
          ingestion, stub embeddings, in-memory vector store, retrieval relevance,
          citation provenance, insufficient-evidence handling, LLM failure mapping,
          and the end-to-end chain - all with PROPOSED interfaces, no production code touched.

STUBS:    Embedder/VectorStore/LLM here are deterministic in-memory stubs. They validate
          the INTERFACE only, not model quality. Replace with real implementations in
          rag/embeddings/, rag/retrieval/ and rag/generation/ later.

RUN:      .venv\\Scripts\\python.exe rag\\tests\\test_rag_contract.py
          (set RAG_TEST_JSONL=<path> to also validate real pipeline output)
"""
import hashlib
import json
import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.models import Chunk, ChunkMetadata  # EXISTING project model (read-only import)

# The ingestion helpers are IMPORTED from the real module rather than redefined
# here: these tests must exercise rag.ingestion.loader itself, not a private
# copy living in the test file. The stub embedder/store/LLM further down stay
# local, because they model interfaces that do not exist in the repo yet.
from rag.ingestion.loader import (  # noqa: E402
    ChunkLoadError,
    RagError,
    load_chunks_jsonl,
    make_chunk_id,
    validate_chunk_semantics,
)


# ======================================================================
# PROPOSED error types (Phase 7/10 contract)
# ======================================================================
# RagError and ChunkLoadError are defined in rag.ingestion.loader and imported
# above - they belong to the ingestion boundary, not to this harness. The
# types below cover stages (embedding, generation, citation) that do not exist
# in the repo yet, so they still live here until their own modules land.


class EmbeddingError(RagError):
    code = "embedding_error"


class GenerationError(RagError):
    code = "generation_error"


class MissingSourceError(RagError):
    code = "missing_source"


# ======================================================================
# PROPOSED ingestion: JSONL loading + validation rules (Phase 4)
# ======================================================================
# Promoted into rag/ingestion/loader.py so that production code and these
# tests share a single implementation. load_chunks_jsonl,
# validate_chunk_semantics and make_chunk_id are imported at the top of this
# file; nothing below redefines them.


# ======================================================================
# PROPOSED stub embedder (Phase 5 interface: embed_texts / dimension)
# ======================================================================
class StubEmbedder:
    name = "stub-hash-bow"
    version = "0"

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.calls = 0

    @staticmethod
    def _tokens(text: str):
        return re.findall(r"[a-z0-9à-ÿ]+", text.lower())

    def embed_texts(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            if not isinstance(t, str) or not t.strip():
                raise EmbeddingError("empty text cannot be embedded")
            vec = [0.0] * self.dim
            for tok in self._tokens(t):
                idx = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:4], "big")
                vec[idx % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    def embed_query(self, text: str):
        # PROPOSED RULE: questions MUST go through the SAME embedder/version.
        return self.embed_texts([text])[0]


# ======================================================================
# PROPOSED in-memory vector store (Phase 6 interface)
# ======================================================================
class InMemoryVectorStore:
    def __init__(self):
        self.rows = {}  # id -> {"vector", "record", "source"}

    @staticmethod
    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)

    def upsert(self, chunk_id, vector, record, source_path):
        existed = chunk_id in self.rows  # idempotent ingestion: same id = overwrite, not append
        self.rows[chunk_id] = {"vector": vector, "record": record, "source": source_path}
        return existed

    def search(self, query_vec, k=5, filters=None):
        hits = []
        for cid, row in self.rows.items():
            rec = row["record"]
            if filters:
                md = rec.metadata
                if any(getattr(md, f, None) != v for f, v in filters.items()):
                    continue
            hits.append((self._cosine(query_vec, row["vector"]), cid, row))
        hits.sort(key=lambda x: -x[0])
        return hits[:k]


# ======================================================================
# PROPOSED retrieval + evidence gate + citation formatting (Phase 7)
# ======================================================================
def retrieve(store, query: str, embedder, k=5, filters=None, min_score=0.05):
    hits = store.search(embedder.embed_query(query), k=k, filters=filters)
    if not hits or hits[0][0] < min_score:
        return []  # insufficient evidence -> caller must NOT fabricate an answer
    return [{"chunk_id": cid, "score": s, **row["record"].model_dump()} for s, cid, row in hits]


def format_citations(hits, source_registry):
    """Citations must point at RETRIEVED records only; unknown sources are an error."""
    out = []
    for h in hits:
        doc = h["metadata"]["document_name"]
        if doc not in source_registry:
            raise MissingSourceError(f"retrieved chunk references unknown document {doc!r}")
        out.append({"chunk_id": h["chunk_id"], "score": round(h["score"], 4),
                    "document_name": doc, "family_type": h["metadata"]["family_type"],
                    "page": h["metadata"]["page"], "sheet_name": h["metadata"]["sheet_name"],
                    "source_path": source_registry[doc]})
    return out


class FakeLLM:
    """Deterministic stand-in for the future generation backend."""
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.attempts = 0

    def complete(self, prompt: str) -> str:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise ConnectionError("provider timeout")
        m = re.search(r"QUESTION:\s*(.+)", prompt)
        return f"(stub answer) Based on the provided context for: {m.group(1) if m else '?'}. [src:1]"


def generate(llm, question: str, hits, retries=2):
    if not hits:
        return {"status": "insufficient_evidence", "answer": None, "sources": []}
    context = "\n---\n".join(h["text"] for h in hits)
    prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}\nANSWER (cite [src:n] only):"
    last = None
    for attempt in range(retries + 1):
        try:
            answer = llm.complete(prompt)
            break
        except Exception as exc:  # provider errors/timeouts -> typed error after retries
            last = exc
    else:
        raise GenerationError(f"LLM failed after {retries + 1} attempts: {last}") from last
    # Strip any [src:n] the model invented that is not in the retrieved set.
    allowed = {f"[src:{i + 1}]" for i in range(len(hits))}
    answer = re.sub(r"\[src:\s*(\d+)\s*\]",
                    lambda m: m.group(0) if m.group(0).replace(" ", "") in allowed else "",
                    answer)
    return {"status": "ok", "answer": answer, "sources": format_citations_stub(hits)}


def format_citations_stub(hits):
    return [{"chunk_id": h["chunk_id"], "document_name": h["metadata"]["document_name"],
             "page": h["metadata"]["page"], "score": round(h["score"], 4)} for h in hits]


def make_rec(text, doc, family="A", **md):
    base = dict(document_name=doc, family_type=family)
    base.update(md)
    return Chunk(text=text, metadata=ChunkMetadata(**base))


def make_store_with(recs):
    emb, store = StubEmbedder(), InMemoryVectorStore()
    vecs = emb.embed_texts([r.text for r in recs])
    for r, v in zip(recs, vecs):
        store.upsert(make_chunk_id(r), v, r, f"sources/{r.metadata.document_name}")
    return emb, store


# ======================================================================
# TESTS
# ======================================================================
class TestJsonlContract(unittest.TestCase):
    def setUp(self):
        self.recs = [
            make_rec("Planning des examens session 1 a Amphi 1", "planning.pdf", "E", page=2),
            make_rec("Liste des etudiants licence 3", "liste.xlsx", "C",
                     sheet_name="Inscrits", block_range="4-10"),
        ]
        self.path = os.path.join(os.path.dirname(__file__), "_tmp_contract.jsonl")
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in self.recs:
                fh.write(json.dumps(r.model_dump(), ensure_ascii=False) + "\n")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_valid_jsonl_loads(self):
        loaded = load_chunks_jsonl(self.path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].metadata.document_name, "planning.pdf")

    def test_malformed_json_rejected_with_line_number(self):
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        with self.assertRaises(ChunkLoadError) as ctx:
            load_chunks_jsonl(self.path)
        self.assertIn("line 3", str(ctx.exception))

    def test_schema_violation_rejected(self):
        bad = os.path.join(os.path.dirname(__file__), "_tmp_bad.jsonl")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"text": "x"}) + "\n")  # no metadata
        try:
            with self.assertRaises(ChunkLoadError):
                load_chunks_jsonl(bad)
        finally:
            os.remove(bad)

    def test_empty_text_rejected(self):
        with self.assertRaises(ChunkLoadError):
            validate_chunk_semantics(make_rec("   ", "d.pdf"))

    def test_empty_document_name_rejected(self):
        with self.assertRaises(ChunkLoadError):
            validate_chunk_semantics(make_rec("text", "  "))

    def test_real_pipeline_output_if_provided(self):
        path = os.environ.get("RAG_TEST_JSONL")
        if not path or not os.path.exists(path):
            self.skipTest("set RAG_TEST_JSONL to a real chunks_output.jsonl")
        recs = load_chunks_jsonl(path)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertTrue(r.metadata.document_name)  # provenance never lost


class TestChunkIdsAndIdempotency(unittest.TestCase):
    def test_ids_stable_across_calls(self):
        r = make_rec("texte stable", "doc.pdf", page=1)
        self.assertEqual(make_chunk_id(r), make_chunk_id(r))

    def test_ids_change_when_text_changes(self):
        a = make_rec("texte A", "doc.pdf")
        b = make_rec("texte B", "doc.pdf")
        self.assertNotEqual(make_chunk_id(a), make_chunk_id(b))

    def test_duplicate_ingestion_is_idempotent(self):
        recs = [make_rec("alpha", "a.pdf"), make_rec("beta", "b.pdf")]
        _, store = make_store_with(recs)
        n = len(store.rows)
        _, store2 = make_store_with(recs + recs)  # same batch twice
        self.assertEqual(len(store2.rows), n)


class TestEmbeddingsAndVectorStore(unittest.TestCase):
    def test_stub_embedding_deterministic_and_dimension(self):
        e = StubEmbedder(dim=32)
        v1, v2 = e.embed_texts(["Bonjour USTHB"]), e.embed_texts(["Bonjour USTHB"])
        self.assertEqual(v1, v2)
        self.assertEqual(len(v1[0]), 32)

    def test_query_and_doc_share_embedding_space(self):
        e = StubEmbedder()
        q, d = e.embed_query("examens planning"), e.embed_texts(["examens planning a session 1"])[0]
        store = InMemoryVectorStore()
        self.assertGreater(store._cosine(q, d), 0.4)

    def test_empty_text_cannot_be_embedded(self):
        with self.assertRaises(EmbeddingError):
            StubEmbedder().embed_texts([""])

    def test_topk_ordering_and_metadata_filter(self):
        recs = [
            make_rec("examens planning session 1", "exam.pdf", "E"),
            make_rec("liste des etudiants licence", "liste.xlsx", "C"),
            make_rec("decret reglement des etudes", "decret.pdf", "A"),
        ]
        emb, store = make_store_with(recs)
        hits = store.search(emb.embed_query("planning examens"), k=3)
        self.assertEqual(hits[0][2]["record"].metadata.document_name, "exam.pdf")
        hits2 = store.search(emb.embed_query("planning examens"), k=3,
                              filters={"family_type": "C"})
        self.assertTrue(all(h[2]["record"].metadata.family_type == "C" for h in hits2))

    def test_retrieval_relevance_keyword_probe(self):
        recs = [
            make_rec("planning des examens session 1 a amphi 1", "exam.pdf", "E"),
            make_rec("liste des etudiants master reseaux", "liste.xlsx", "C"),
            make_rec("arrete universitaire portant organisation", "arrete.pdf", "F"),
        ]
        emb, store = make_store_with(recs)
        top = store.search(emb.embed_query("planning des examens"), k=1)
        self.assertEqual(top[0][2]["record"].metadata.document_name, "exam.pdf")


class TestEvidenceAndCitations(unittest.TestCase):
    def test_insufficient_evidence_yields_no_answer(self):
        recs = [make_rec("planning examens amphi", "exam.pdf")]
        emb, store = make_store_with(recs)
        hits = retrieve(store, "xylophone quantique interstellaire", emb, min_score=0.05)
        result = generate(FakeLLM(), "xylophone quantique interstellaire", hits)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIsNone(result["answer"])

    def test_missing_source_raises(self):
        recs = [make_rec("texte", "ghost.pdf")]
        emb, store = make_store_with(recs)
        hits = retrieve(store, "texte", emb)
        with self.assertRaises(MissingSourceError):
            format_citations(hits, source_registry={})  # ghost.pdf not registered

    def test_citations_only_from_retrieved_set(self):
        recs = [make_rec("planning examens amphi", "exam.pdf")]
        emb, store = make_store_with(recs)
        hits = retrieve(store, "planning examens", emb)
        result = generate(FakeLLM(), "Quand sont les examens ?", hits)
        self.assertEqual(result["status"], "ok")
        cited = {s["chunk_id"] for s in result["sources"]}
        self.assertEqual(cited, {h["chunk_id"] for h in hits})
        self.assertNotIn("[src:9]", result["answer"])  # hallucinated citation stripped

    def test_llm_failures_retried_then_typed_error(self):
        llm = FakeLLM(fail_times=99)
        with self.assertRaises(GenerationError):
            generate(llm, "q", [{"text": "ctx", "chunk_id": "c",
                                 "metadata": {"document_name": "d", "family_type": "A",
                                              "page": None, "sheet_name": None}}], retries=1)
        self.assertEqual(llm.attempts, 2)

    def test_end_to_end_chain_with_stubs(self):
        recs = [
            make_rec("planning des examens session 1 amphi 1", "exam.pdf", "E", page=1),
            make_rec("liste des etudiants licence 3 informatique", "liste.xlsx", "C"),
        ]
        emb, store = make_store_with(recs)
        registry = {"exam.pdf": "corpus/exam.pdf", "liste.xlsx": "corpus/liste.xlsx"}
        hits = retrieve(store, "planning des examens", emb, k=2)
        result = generate(FakeLLM(), "planning des examens", hits)
        self.assertEqual(result["status"], "ok")
        for s in result["sources"]:
            self.assertIn(s["document_name"], registry)
            self.assertIn(s["chunk_id"], {h["chunk_id"] for h in hits})


if __name__ == "__main__":
    unittest.main(verbosity=2)
