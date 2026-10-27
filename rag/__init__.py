"""RAG layer for RAG-USTHB.

This package is the bridge between the document-processing pipeline and the
future retrieval stage. It intentionally contains **no** pipeline code: the
pipeline owns ``main.py``, ``pipeline/``, ``parsers/`` and ``core/``.

Current contents
----------------
``rag.ingestion``  Loading, validation and identity of pipeline JSONL output.
``rag.tests``      Contract tests that pin the pipeline-to-RAG data contract.

Planned (not yet implemented) --------------------------------------------
``rag.embedding``  Chunk -> vector, batching, model versioning.
``rag.store``       Vector persistence and metadata filtering.
``rag.retrieval``   Query embedding, similarity search, thresholds.
``rag.prompts``     Generation and citation assembly.

Only the ingestion module is implemented today; everything else is a stub
directory (``embeddings/``, ``retrieval/``, ``generation/``, ``prompts/``)
holding nothing but ``.gitkeep``. Do not assume an import will succeed until
the module ships real code.
"""

__all__ = ["ingestion"]
