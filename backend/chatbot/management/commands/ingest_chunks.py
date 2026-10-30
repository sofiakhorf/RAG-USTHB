"""Ingest the preprocessing JSONL exports into the Django knowledge base.

This is the missing final stage of the pipeline::

    main.py -> Chunks_family/*.jsonl -> [rag.ingestion] -> [rag.embeddings] -> HERE

It deliberately reuses, and does not reimplement, the three components that
already exist:

* :func:`rag.ingestion.loader.load_chunks_jsonl`   - read + validate the export
* :func:`rag.ingestion.loader.make_chunk_id`       - the stable, content-addressed id
* :func:`rag.ingestion.loader.validate_chunk_semantics`
* :func:`rag.embeddings.encoder.embed_chunks`-time helpers ``load_embedding_model``
  / ``create_embeddings`` / ``validate_embeddings`` - the model and its checks

Everything here is **idempotent**. Chunk identity comes from ``make_chunk_id``,
so re-running the command on unchanged input updates rows in place and creates
nothing. Embeddings that are already stored, produced by the same model, with
the right width and finite values, are reused instead of being recomputed.

Stale chunks are **not** deleted unless ``--prune`` is passed (destructive;
requires an explicit decision).

    python manage.py ingest_chunks
    python manage.py ingest_chunks --source ..\\preprocessing\\Chunks_family
    python manage.py ingest_chunks --dry-run
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction

from chatbot.models import Chunk, Document, Embedding
from core.models import Chunk as PipelineChunk
from rag.embeddings.encoder import (
    MODEL_DIMENSION,
    MODEL_NAME,
    create_embeddings,
    load_embedding_model,
    validate_embeddings,
)
from rag.ingestion import ChunkLoadError, load_chunks_jsonl, make_chunk_id, validate_chunk_semantics

#: Where ``main.py`` writes its per-family exports. The pipeline's own default
#: output dir is ``Chunks_family``; in this checkout the exports live under
#: ``preprocessing/``.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE = REPO_ROOT / "preprocessing" / "Chunks_family"


class Command(BaseCommand):
    help = "Ingest Chunks_family/*.jsonl into chatbot_document / chatbot_chunk / chatbot_embedding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=str(DEFAULT_SOURCE),
            help=f"Directory holding the JSONL exports (default: {DEFAULT_SOURCE})",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=64,
            help="Chunks encoded per forward pass (default: 64).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate, embed and report what would be written, without touching the database.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help=(
                "Delete chunks a document no longer produces, and cascade-delete "
                "their embeddings. Off by default because it is destructive."
            ),
        )

    def handle(self, *args, **opts):
        source = Path(opts["source"])
        if not source.is_dir():
            raise CommandError(f"Source directory not found: {source}")

        files = sorted(source.glob("*.jsonl"))
        if not files:
            raise CommandError(f"No *.jsonl exports found in {source}")

        dry = opts["dry_run"]
        prune = opts["prune"]

        self.stdout.write(f"Source   : {source}")
        self.stdout.write(f"Files    : {len(files)}")
        self.stdout.write(f"Model    : {MODEL_NAME} ({MODEL_DIMENSION}d)")
        self.stdout.write(f"Dry run  : {dry}")
        self.stdout.write(f"Prune    : {prune}")
        self.stdout.write("")

        records, per_file = self._load_all(files)
        documents = self._group_documents(records)
        self.stdout.write(
            f"Loaded {len(records)} valid chunks -> {len(documents)} documents\n"
        )

        vectors, reused, encoded = self._embed(records, opts["batch_size"])
        stats = self._persist(
            documents, vectors, source=source, dry=dry, prune=prune
        )
        self._report(per_file, reused, encoded, stats, dry)

    def _load_all(self, files):
        """Read every export, reusing the pipeline validators.

        Fully valid files go through :func:`load_chunks_jsonl` (all-or-nothing).
        If that rejects a file, fall back to per-line validation so valid
        records are still ingested and invalid ones are counted.
        """
        records, per_file = [], {}
        for path in files:
            recs, invalid = self._load_file(path)
            per_file[path.name] = {
                "valid": len(recs),
                "invalid": invalid,
            }
            records.extend(recs)
            self.stdout.write(
                f"  {path.name:32s} {len(recs):5d} valid  {invalid:5d} invalid"
            )
        self.stdout.write("")
        return records, per_file

    def _load_file(self, path):
        try:
            recs = load_chunks_jsonl(str(path))
            return recs, 0
        except (ChunkLoadError, OSError, json.JSONDecodeError):
            return self._load_file_tolerant(path)

    def _load_file_tolerant(self, path):
        records = []
        invalid = 0
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    rec = PipelineChunk.model_validate(obj)
                    validate_chunk_semantics(rec, lineno)
                except Exception as exc:
                    invalid += 1
                    self.stderr.write(
                        self.style.WARNING(f"  {path.name} line {lineno}: {exc}")
                    )
                    continue
                records.append(rec)
        return records, invalid

    @staticmethod
    def _group_documents(records):
        """Bucket chunks by ``(family_type, document_name)`` = one Document row."""
        docs = defaultdict(list)
        for rec in records:
            docs[(rec.metadata.family_type, rec.metadata.document_name)].append(rec)
        return dict(docs)

    def _embed(self, records, batch_size):
        """Encode only chunks whose stored vector is missing or unusable."""
        wanted = {make_chunk_id(r) for r in records}

        close_old_connections()
        reusable = set()
        if wanted:
            # Do not fetch every JSON vector in one round-trip: 1181 x 384
            # floats through a pooled SSL connection times out. Identify
            # candidates by model/width first, then validate vectors in batches.
            candidates = list(
                Embedding.objects.filter(
                    chunk__chunk_id__in=wanted,
                    model_name=MODEL_NAME,
                    dimensions=MODEL_DIMENSION,
                ).values_list("chunk__chunk_id", flat=True)
            )
            batch_n = 32
            for start in range(0, len(candidates), batch_n):
                batch = candidates[start : start + batch_n]
                for cid, vec, model_name, dims in Embedding.objects.filter(
                    chunk__chunk_id__in=batch
                ).values_list("chunk__chunk_id", "embedding", "model_name", "dimensions"):
                    if _vector_is_reusable(vec, model_name, dims):
                        reusable.add(cid)

        todo = [r for r in records if make_chunk_id(r) not in reusable]
        seen, unique_todo = set(), []
        for rec in todo:
            cid = make_chunk_id(rec)
            if cid not in seen:
                seen.add(cid)
                unique_todo.append(rec)

        self.stdout.write(
            f"Embeddings: {len(wanted)} needed, {len(reusable)} reusable, "
            f"{len(unique_todo)} to encode\n"
        )

        if not unique_todo:
            return {}, len(reusable), 0

        model = load_embedding_model()
        started = time.time()
        vectors = create_embeddings(
            [r.text for r in unique_todo],
            model,
            batch_size=batch_size,
            show_progress_bar=False,
        )
        dimension = validate_embeddings(vectors, unique_todo)
        if dimension != MODEL_DIMENSION:
            raise CommandError(
                f"Encoder produced {dimension}-d vectors, expected {MODEL_DIMENSION}. "
                "An existing index would be incompatible with these vectors."
            )

        mapping = {make_chunk_id(r): v for r, v in zip(unique_todo, vectors)}
        self.stdout.write(
            f"Encoded {len(unique_todo)} chunks in {time.time() - started:.1f}s "
            f"({dimension}d, validated)\n"
        )
        return mapping, len(reusable), len(unique_todo)

    def _persist(self, documents, vectors, source, dry, prune):
        stats = Counter()
        by_family = defaultdict(Counter)
        title_max = Document._meta.get_field("title").max_length

        for (family, doc_name), recs in sorted(documents.items()):
            ordered, seen = [], set()
            for rec in recs:
                cid = make_chunk_id(rec)
                if cid in seen:
                    stats["chunks_deduplicated"] += 1
                    continue
                seen.add(cid)
                ordered.append((cid, rec))

            file_hash = hashlib.sha256(
                "|".join(sorted(seen)).encode("utf-8")
            ).hexdigest()
            title = doc_name[:title_max]

            if dry:
                stats["documents"] += 1
                stats["chunks"] += len(ordered)
                stats["embeddings"] += len(ordered)
                by_family[family]["documents"] += 1
                by_family[family]["chunks"] += len(ordered)
                continue

            with transaction.atomic():
                doc, created = self._get_or_update_document(
                    family=family,
                    title=title,
                    doc_name=doc_name,
                    file_hash=file_hash,
                    source=source,
                )
                stats["documents_created" if created else "documents_updated"] += 1
                stats["documents"] += 1

                incoming = set(seen)
                if prune:
                    stale = list(
                        doc.chunks.exclude(chunk_id__in=incoming).values_list(
                            "chunk_id", flat=True
                        )
                    )
                    if stale:
                        doc.chunks.filter(chunk_id__in=stale).delete()
                        stats["chunks_pruned"] += len(stale)

                existing = {
                    row.chunk_id: row.chunk_index
                    for row in doc.chunks.only("chunk_id", "chunk_index")
                }
                used_indices = set(existing.values())
                next_index = (max(used_indices) + 1) if used_indices else 0

                for cid, rec in ordered:
                    if cid in existing:
                        index = existing[cid]
                    else:
                        while next_index in used_indices:
                            next_index += 1
                        index = next_index
                        used_indices.add(index)
                        existing[cid] = index
                        next_index += 1

                    meta = rec.metadata
                    page = meta.page
                    chunk, c_created = Chunk.objects.update_or_create(
                        chunk_id=cid,
                        defaults={
                            "document": doc,
                            "chunk_index": index,
                            "text": rec.text,
                            "document_name": (meta.document_name or "")[:255],
                            "family_type": (meta.family_type or "")[:100],
                            "procedure": (meta.procedure or "")[:255],
                            "formation": (meta.formation or "")[:255],
                            "niveau": (meta.niveau or "")[:100],
                            "semestre": (meta.semestre or "")[:100],
                            "ue": (meta.ue or "")[:255],
                            "matiere": (meta.matiere or "")[:255],
                            "annee_universitaire": (meta.annee_universitaire or "")[:50],
                            "page": page if (isinstance(page, int) and page >= 0) else None,
                            "sheet_name": (meta.sheet_name or "")[:255],
                            "block_range": (meta.block_range or "")[:255],
                            "block_title": (meta.block_title or "")[:255],
                            "chapter": (meta.chapter or "")[:255],
                            "article_title": (meta.article_title or "")[:255],
                            "article_number": (
                                "" if meta.article_number is None else str(meta.article_number)[:100]
                            ),
                            "language": (meta.language or "")[:20],
                            "is_fallback": bool(meta.is_fallback),
                            "metadata": meta.model_dump(mode="json"),
                        },
                    )
                    stats["chunks_created" if c_created else "chunks_updated"] += 1
                    stats["chunks"] += 1

                    vector = vectors.get(cid)
                    if vector is None:
                        exists = Embedding.objects.filter(chunk=chunk).exists()
                        if not exists:
                            raise CommandError(
                                f"No vector available for chunk {cid} and none stored."
                            )
                        stats["embeddings_reused"] += 1
                    else:
                        Embedding.objects.update_or_create(
                            chunk=chunk,
                            defaults={
                                "embedding": vector,
                                "model_name": MODEL_NAME,
                                "dimensions": len(vector),
                            },
                        )
                        stats["embeddings_written"] += 1
                    stats["embeddings"] += 1
                    by_family[family]["chunks"] += 1

                by_family[family]["documents"] += 1

        stats["__by_family__"] = dict(by_family)
        return stats

    @staticmethod
    def _get_or_update_document(family, title, doc_name, file_hash, source):
        """Idempotent Document row keyed by family_type + title.

        There is no unique constraint on those columns (schema is frozen), so
        a filter-then-update is used instead of ``update_or_create`` to avoid
        creating a second row when duplicates already exist.
        """
        matches = list(
            Document.objects.filter(family_type=family, title=title).order_by("created_at")
        )
        defaults = {
            "original_filename": doc_name[:255],
            "stored_path": str(source)[:500],
            "file_hash": file_hash,
            "mime_type": "application/x-ndjson",
            "status": "processed",
            "error_message": "",
            "metadata": {
                "source": "preprocessing_pipeline",
                "document_name": doc_name,
            },
        }
        if not matches:
            doc = Document.objects.create(family_type=family, title=title, **defaults)
            return doc, True

        doc = matches[0]
        for field, value in defaults.items():
            setattr(doc, field, value)
        doc.save(update_fields=list(defaults))
        return doc, False

    def _report(self, per_file, reused, encoded, stats, dry):
        self.stdout.write("\n" + "=" * 74)
        self.stdout.write("PER-FILE CHUNKS")
        for name, counts in per_file.items():
            self.stdout.write(
                f"  {name:34s} valid={counts['valid']:5d}  invalid={counts['invalid']:5d}"
            )

        self.stdout.write("\nBY family_type")
        self.stdout.write(f"  {'family':8s} {'documents':>10s} {'chunks':>8s}")
        for family in sorted(stats["__by_family__"]):
            row = stats["__by_family__"][family]
            self.stdout.write(
                f"  {family:8s} {row['documents']:>10d} {row['chunks']:>8d}"
            )

        label = "WOULD WRITE" if dry else "TOUCHED"
        self.stdout.write("\nTOTALS")
        self.stdout.write(f"  documents {label:12s} : {stats['documents']}")
        self.stdout.write(f"  documents created          : {stats['documents_created']}")
        self.stdout.write(f"  documents updated          : {stats['documents_updated']}")
        self.stdout.write(f"  chunks {label:15s} : {stats['chunks']}")
        self.stdout.write(f"  chunks created             : {stats['chunks_created']}")
        self.stdout.write(f"  chunks updated             : {stats['chunks_updated']}")
        self.stdout.write(f"  chunks deduplicated in file: {stats['chunks_deduplicated']}")
        self.stdout.write(f"  chunks pruned (stale)      : {stats['chunks_pruned']}")
        self.stdout.write(f"  embeddings encoded         : {encoded}")
        self.stdout.write(f"  embeddings reusable in db  : {reused}")
        self.stdout.write(f"  embeddings {label:12s} : {stats['embeddings']}")
        self.stdout.write(f"  embeddings written         : {stats['embeddings_written']}")
        self.stdout.write(f"  embeddings reused in store : {stats['embeddings_reused']}")
        self.stdout.write("=" * 74)

        if stats["chunks_pruned"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{stats['chunks_pruned']} stale chunk(s) were deleted because "
                    "--prune was set. Their embeddings were cascade-deleted with them."
                )
            )


def _vector_is_reusable(vec, model_name, dims) -> bool:
    return (
        model_name == MODEL_NAME
        and dims == MODEL_DIMENSION
        and isinstance(vec, list)
        and len(vec) == MODEL_DIMENSION
        and all(isinstance(x, (int, float)) and math.isfinite(x) for x in vec)
    )
