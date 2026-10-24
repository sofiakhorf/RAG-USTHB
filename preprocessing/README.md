# Preprocessing Pipeline

Document ingestion, routing, parsing, and text-cleaning pipeline for heterogeneous
academic and administrative files (PDF, DOCX, XLSX, JPG/PNG, VSDX, draw.io).

## Status: directory scaffold only — existing code stays at repository root

The entire existing preprocessing implementation **already lives at the repository
root** and is actively working code. It was **intentionally left in place** because
moving it under `preprocessing/` would break imports, paths, configuration, and
execution (details below). No source file contents were changed.

### Existing code (at repo root) → mapped to this module's planned subdirectories

| Existing location (repo root)        | Role                       | Planned home (future)   |
|--------------------------------------|----------------------------|-------------------------|
| `parsers/` (family_a … family_j, fallback) | `parsers/`          | `preprocessing/parsers/`    |
| `pipeline/router.py`                 | Document classification & extraction | `preprocessing/extraction/` |
| `core/utils.py`, `pipeline/` cleaning steps | Text cleaning     | `preprocessing/cleaning/`   |
| `core/models.py` (`Chunk`, `ChunkMetadata`) | Chunking        | `preprocessing/chunking/`   |
| `core/` (models, registry, exceptions, utils) | Shared core   | stays at root for now       |
| `config/` (pydantic `Settings`)      | Pipeline configuration     | stays at root for now       |
| `fi_scraper/` + `scrapy.cfg`         | Scrapy web scraper (source acquisition) | stays at root for now |
| `main.py`                            | CLI entry point            | stays at root for now       |
| `data/` (root, git-ignored)          | Raw input datasets         | see "Data" section below    |

### Why the existing files were not moved

Moving these files under `preprocessing/` would break the project:

1. **Absolute root-level imports.** `main.py`, `pipeline/`, `parsers/`, `core/`,
   and `config/` import each other as top-level packages
   (`from core import …`, `from parsers import …`, `from pipeline import …`,
   `from config import …`). Moving them requires rewriting every import —
   forbidden by the task's safety rules.
2. **Filesystem paths computed from `__file__`.** `core/__init__.py` and
   `pipeline/router.py` resolve the OCR language data as
   `Path(__file__).resolve().parent.parent / "tessdata"`, i.e. a `tessdata/`
   directory **at the repository root**. Moving the packages would silently change
   that target to `preprocessing/tessdata/` and disable OCR language data lookup.
3. **Scrapy configuration.** Root `scrapy.cfg` declares
   `default = fi_scraper.settings`; the Scrapy CLI must run from the directory
   containing `scrapy.cfg` with `fi_scraper` importable from that same root.
4. **CWD-relative configuration.** `config/settings.py` loads `.env` relative to
   the working directory (repo root), `main.py` defaults to `--input-dir data`
   (root `data/`), and the scraper spider writes downloads to `./downloads/`.
5. **`.gitignore` patterns** are written for root paths (`data/*`,
   `!data/.gitkeep`, `chunks_output.jsonl`).

A safe future migration would need an atomic refactor (imports, `__file__` paths,
`scrapy.cfg`, `.gitignore`, CLI invocation) — out of scope for this structure-only pass.

### Planned subdirectories (placeholders created)

- `parsers/` — future home of the family parsers (root `parsers/` currently serves this role).
- `extraction/` — layout/text/metadata extraction.
- `cleaning/` — text normalization and cleaning.
- `chunking/` — chunking strategies producing `Chunk` records (JSONL output).
- `data/` — **small, non-sensitive sample data or documented local data paths only.**

### Data

Root `data/` is the real dataset directory and is **git-ignored** (`data/*`, only
`data/.gitkeep` is tracked). Datasets must stay out of Git; do **not** copy them
into `preprocessing/data/`. `preprocessing/data/` is reserved for tiny sample files
or a README documenting local data paths.

### Running the pipeline (unchanged)

```bash
python main.py --input-dir data --output-file chunks_output.jsonl
```

Dependencies remain in the root `requirements.txt` (unchanged).
