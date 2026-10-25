# RAG Module (embeddings / retrieval / generation / prompts)

Retrieval-Augmented Generation pipeline for the chatbot. **Scaffold only — no RAG
logic implemented yet**, per the structure-only scope of this pass.

## Planned subdirectories (placeholders created)

- `embeddings/` — embedding model integration and vector store indexing.
- `retrieval/` — similarity search over the pgvector index, query preprocessing.
- `generation/` — LLM prompting and answer generation with retrieved context.
- `prompts/` — prompt templates.

## Planned technology (not configured at this stage)

- Vector store: **Supabase / PostgreSQL + pgvector**
- Input: `Chunk` records (Pydantic) exported by the preprocessing pipeline
  (`main.py` → `chunks_output.jsonl`, schema in root `core/models.py`)

## Notes

- No database connections, credentials, embeddings, or prompt implementations were
  created in this pass.
- ⚠️ The repository root `.gitignore` currently ignores every directory named
  `prompts/` (pattern: `prompts/`). Therefore `rag/prompts/` will **not** be
  tracked by Git until an exception such as `!rag/prompts/` is added to
  `.gitignore`. This was left as a manual step to avoid modifying an existing file.
