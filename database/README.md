# Database (Supabase / PostgreSQL / pgvector)

Planned storage layer for documents, chat sessions/messages, users, and vector
embeddings. **Scaffold only** — no tables, credentials, connections, or migrations
were created or modified in this pass.

## Planned subdirectories (placeholders created)

- `schema/` — SQL schema documentation for Supabase/PostgreSQL + pgvector.
- `migrations/` — future migration scripts.
- Documentation of the vector index (pgvector) and metadata columns mapped from
  `ChunkMetadata` (see root `core/models.py`).

## Safety rules applied

- No database tables created.
- No migrations written or modified.
- No credentials or connection strings added (`.env` untouched; see root
  `.env.example` for non-secret key placeholders only).

## Notes

- Remote branch `origin/DataBase` exists but its contents are identical to
  `origin/main` (preprocessing pipeline only) — no database project was found in it.
