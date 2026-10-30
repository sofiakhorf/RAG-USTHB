"""
RETRIEVAL TESTS - RAG-USTHB.
============================
PURPOSE:  Executable specification of ``rag/retrieval``, the stage that ranks
          indexed chunks against a query vector. Unlike the API tests in
          ``backend/``, nothing here needs Django, a database or a model
          download, so the ranking maths can be verified in isolation.

RUN:      .venv\\Scripts\\python.exe rag\\tests\\test_retrieval.py

What is covered
---------------
* ``cosine_similarity`` - the identity, orthogonality, opposition, the
  undefined zero-magnitude case, and dimension mismatch.
* ``rank_candidates``   - ordering, ``top_k``, the ``min_score`` cutoff that
  turns "nothing relevant" into an honest empty result, deterministic tie
  breaking, and rejection of malformed stored vectors.
* ``RetrievalResult`` / ``RetrievedChunk`` - the small helpers the API layer
  relies on for citations.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from rag.retrieval import (  # noqa: E402
    Candidate,
    DimensionMismatchError,
    RetrievalError,
    RetrievalResult,
    RetrievedChunk,
    cosine_similarity,
    rank_candidates,
)


def candidate(chunk_id, vector, **kwargs):
    """Build a Candidate with sensible defaults for the common case."""
    kwargs.setdefault("text", f"text of {chunk_id}")
    kwargs.setdefault("document_name", "Syllabus")
    return Candidate(chunk_id=chunk_id, vector=vector, **kwargs)


class TestCosineSimilarity(unittest.TestCase):
    """``cosine_similarity``."""

    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)

    def test_magnitude_does_not_matter(self):
        """Cosine compares direction, not length - so unnormalised rows still work."""
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [10.0, 20.0]), 1.0)

    def test_orthogonal_vectors_score_zero(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposite_vectors_score_minus_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [-1.0, -2.0]), -1.0)

    def test_zero_magnitude_vector_scores_zero_rather_than_raising(self):
        """Cosine is undefined for a directionless vector; it must not crash.

        A single degenerate embedding should degrade one result, not take down
        the whole search.
        """
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0, 2.0], [0.0, 0.0]), 0.0)

    def test_result_is_always_finite_and_bounded(self):
        """No input may produce NaN or escape [-1, 1]."""
        vectors = [
            ([1.0, 1.0], [1.0, 1.0]),
            ([1.0, -1.0], [1.0, 1.0]),
            ([0.5, 0.5], [2.0, -2.0]),
            ([-3.0, -4.0], [5.0, -6.0]),
        ]
        for left, right in vectors:
            score = cosine_similarity(left, right)
            self.assertTrue(math.isfinite(score), f"{left} vs {right} -> {score}")
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)

    def test_dimension_mismatch_is_rejected(self):
        """Silently truncating to the shorter length would corrupt every score."""
        with self.assertRaises(DimensionMismatchError):
            cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0])

    def test_integer_vectors_are_accepted(self):
        """Stored JSON may decode as ints; that is still a valid vector."""
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)


class TestRankCandidates(unittest.TestCase):
    """``rank_candidates``."""

    def test_orders_by_score_descending(self):
        result = rank_candidates(
            [1.0, 0.0],
            [
                candidate("c", [0.0, 1.0]),      # orthogonal -> 0.0
                candidate("a", [1.0, 0.0]),      # identical  -> 1.0
                candidate("b", [0.7, 0.7]),      # in between
            ],
            min_score=-1.0,
        )

        self.assertEqual(result.chunk_ids, ("a", "b", "c"))

    def test_top_k_truncates(self):
        result = rank_candidates(
            [1.0, 0.0],
            [
                candidate("a", [1.0, 0.0]),
                candidate("b", [0.9, 0.1]),
                candidate("c", [0.8, 0.2]),
                candidate("d", [0.7, 0.3]),
                candidate("e", [0.6, 0.4]),
            ],
            top_k=2,
            min_score=-1.0,
        )

        self.assertEqual(result.chunk_ids, ("a", "b"))

    def test_default_top_k_is_applied(self):
        candidates = [candidate(f"c{i}", [1.0, i / 10]) for i in range(10)]

        result = rank_candidates([1.0, 0.0], candidates, min_score=-1.0)

        self.assertEqual(len(result.chunks), 4)

    def test_zero_or_negative_top_k_returns_nothing(self):
        """A caller asking for nothing must get nothing, not an error."""
        result = rank_candidates([1.0, 0.0], [candidate("a", [1.0, 0.0])], top_k=0)

        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunks, ())

    def test_min_score_drops_unrelated_passages(self):
        """The cutoff is what turns "index is empty" into "no evidence".

        Without it, an unrelated question would still cite the closest chunks
        and look confidently correct.
        """
        result = rank_candidates(
            [1.0, 0.0],
            [
                candidate("related", [1.0, 0.0]),
                candidate("unrelated", [0.0, 1.0]),
            ],
            min_score=0.5,
        )

        self.assertEqual(result.chunk_ids, ("related",))

    def test_all_below_threshold_yields_an_empty_result_not_an_error(self):
        result = rank_candidates(
            [1.0, 0.0],
            [candidate("a", [0.0, 1.0]), candidate("b", [-1.0, 0.0])],
            min_score=0.5,
        )

        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunks, ())

    def test_empty_candidate_list_yields_an_empty_result(self):
        """An unpopulated knowledge base is a normal state, not a failure."""
        result = rank_candidates([1.0, 0.0], [], min_score=0.0)

        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunk_ids, ())

    def test_ties_break_deterministically_on_chunk_id(self):
        """The same query must always return the same order.

        Sorting on score alone would leave exact ties in insertion order,
        which makes retrieval tests flaky and answers non-reproducible.
        """
        tied = [
            candidate("zzz", [1.0, 0.0]),
            candidate("aaa", [1.0, 0.0]),
            candidate("mmm", [1.0, 0.0]),
        ]

        forwards = rank_candidates([1.0, 0.0], tied, min_score=-1.0)
        backwards = rank_candidates([1.0, 0.0], list(reversed(tied)), min_score=-1.0)

        self.assertEqual(forwards.chunk_ids, ("aaa", "mmm", "zzz"))
        self.assertEqual(forwards.chunk_ids, backwards.chunk_ids)

    def test_query_text_is_echoed_into_the_result(self):
        result = rank_candidates([1.0, 0.0], [], query="what is BCNF?")

        self.assertEqual(result.query, "what is BCNF?")

    def test_empty_query_vector_is_rejected(self):
        with self.assertRaises(RetrievalError):
            rank_candidates([], [candidate("a", [1.0])])

    def test_non_finite_query_vector_is_rejected(self):
        """One NaN would silently poison every score."""
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(RetrievalError):
                rank_candidates([1.0, bad], [candidate("a", [1.0, 0.0])])

    def test_non_finite_candidate_vector_is_rejected(self):
        """A corrupt stored row is surfaced, never silently skipped."""
        with self.assertRaises(RetrievalError):
            rank_candidates(
                [1.0, 0.0],
                [candidate("broken", [1.0, float("nan")])],
            )

    def test_empty_candidate_vector_is_rejected(self):
        with self.assertRaises(RetrievalError):
            rank_candidates([1.0, 0.0], [candidate("broken", [])])

    def test_dimension_mismatch_in_a_candidate_is_rejected(self):
        """One bad row must not quietly shrink the knowledge base."""
        with self.assertRaises(DimensionMismatchError):
            rank_candidates(
                [1.0, 0.0, 0.0],
                [candidate("wrong_dims", [1.0, 0.0])],
            )

    def test_scores_are_carried_through(self):
        result = rank_candidates(
            [1.0, 0.0], [candidate("a", [1.0, 0.0])], min_score=-1.0
        )

        self.assertAlmostEqual(result.chunks[0].score, 1.0)

    def test_text_and_metadata_are_carried_through(self):
        result = rank_candidates(
            [1.0, 0.0],
            [
                candidate(
                    "a",
                    [1.0, 0.0],
                    text="the passage itself",
                    document_name="Algebre S3",
                    page=12,
                    metadata={"matiere": "Algebre"},
                )
            ],
            min_score=-1.0,
        )

        chunk = result.chunks[0]
        self.assertEqual(chunk.text, "the passage itself")
        self.assertEqual(chunk.document_name, "Algebre S3")
        self.assertEqual(chunk.page, 12)
        self.assertEqual(chunk.metadata["matiere"], "Algebre")

    def test_ranking_is_not_mutated_by_repeated_calls(self):
        """Calling twice with the same input gives the same output."""
        candidates = [candidate("a", [1.0, 0.0]), candidate("b", [0.5, 0.5])]

        first = rank_candidates([1.0, 0.0], candidates, min_score=-1.0)
        second = rank_candidates([1.0, 0.0], candidates, min_score=-1.0)

        self.assertEqual(first.chunk_ids, second.chunk_ids)


class TestRetrievedChunkAndResult(unittest.TestCase):
    """The small helpers the API layer builds citations from."""

    def test_is_empty_flags_an_unpopulated_index(self):
        self.assertTrue(RetrievalResult(query="q").is_empty)
        self.assertFalse(
            RetrievalResult(
                query="q",
                chunks=(RetrievedChunk(chunk_id="a", score=0.5),),
            ).is_empty
        )

    def test_citation_includes_the_page_when_known(self):
        chunk = RetrievedChunk(
            chunk_id="a", score=0.9, document_name="Syllabus SI S6", page=4
        )

        self.assertEqual(chunk.citation, "Syllabus SI S6, p. 4")

    def test_citation_omits_the_page_when_unknown(self):
        chunk = RetrievedChunk(chunk_id="a", score=0.9, document_name="Syllabus")

        self.assertEqual(chunk.citation, "Syllabus")

    def test_citation_falls_back_to_the_document_name_in_metadata(self):
        chunk = RetrievedChunk(
            chunk_id="a", score=0.9, metadata={"document_name": "From metadata"}
        )

        self.assertEqual(chunk.citation, "From metadata")

    def test_citation_is_never_blank(self):
        """A source label is always present, so the UI has something to render."""
        chunk = RetrievedChunk(chunk_id="a", score=0.9)

        self.assertEqual(chunk.citation, "<unknown source>")


class TestCandidateDefaults(unittest.TestCase):
    """``Candidate`` construction."""

    def test_optional_fields_have_sane_defaults(self):
        chunk = Candidate(chunk_id="a", vector=[1.0])

        self.assertEqual(chunk.text, "")
        self.assertEqual(chunk.document_name, "")
        self.assertIsNone(chunk.page)
        self.assertEqual(chunk.metadata, {})

    def test_results_are_immutable(self):
        """Frozen dataclasses keep a shared result from being edited in place."""
        with self.assertRaises(Exception):
            chunk = RetrievedChunk(chunk_id="a", score=1.0)
            chunk.score = 0.0


if __name__ == "__main__":
    unittest.main(verbosity=2)
