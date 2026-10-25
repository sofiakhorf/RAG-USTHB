# Backend (Python / Django / Django REST Framework)

API service for RAG-USTHB: authentication, user profiles, chat sessions/messages,
document uploads, and integration with the preprocessing + RAG pipelines.

**Scaffold only** — no Django project or applications were created, and no models,
serializers, views, or endpoints were implemented in this pass. (Django is not yet
listed in the root `requirements.txt`; dependencies are not installed per the
safety rules.)

## Planned layout (directory placeholders created)

```
backend/
├── config/            # Django project settings (settings/urls/wsgi/asgi)
├── apps/
│   ├── users/         # Authentication (Keycloak integration) & student profiles
│   ├── chatbot/       # Chat sessions, messages, chatbot API
│   └── documents/     # Document uploads, metadata, processing status
├── api/               # Shared API layer (routing, common serializers/permissions)
├── manage.py          # to be created by django-admin startproject (manual step)
├── requirements.txt   # to be created when Django is added (manual step)
└── README.md          # this file
```

## Relationship to existing code (left untouched at repository root)

- `preprocessing` pipeline (root `parsers/`, `pipeline/`, `core/`, `config/`,
  `main.py`) — invoked by the backend later (e.g., as a subprocess or task) to
  process uploaded documents into `Chunk` JSONL output.
- `rag/` module — consumed for retrieval/generation once implemented.
- Planned backend modules per the MVP: `users`, `chatbot`, `documents`,
  plus adapters for `preprocessing` and `rag`.

## Manual steps (not performed in this structure-only pass)

1. `django-admin startproject config .` inside `backend/` (project package = `config/`).
2. `python manage.py startapp users|chatbot|documents` inside `backend/apps/`
   (or author the app packages manually to match this layout).
3. Add Django + DRF to a backend-specific `requirements.txt`.
4. Configure Supabase/PostgreSQL connection via environment variables only.

## Notes

- Remote branch `origin/Backend` exists but its contents are identical to
  `origin/main` (preprocessing pipeline only) — no Django project was found in it.
- The root `config/` package is the **preprocessing** pydantic settings module and
  is unrelated to this planned Django `config/` package — no conflict, different
  import roots.
