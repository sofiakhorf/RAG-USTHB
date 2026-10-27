# Backend — Django scaffold (no features yet)

A **clean Django project plus database configuration only.** Registration, login,
conversations, chatbot endpoints, retrieval, generation and ingestion are *not*
implemented here — that is deliberate. They are yours to build later.

The existing RAG/preprocessing code at the repository root (`rag/`, `core/`,
`parsers/`, `pipeline/`) is untouched and has nothing to do with Django yet.

---

## 1. Layout

```
backend/
├── manage.py
├── config/                      # Django project package
│   ├── settings.py              # env-driven settings + PostgreSQL config
│   ├── urls.py                  # only /admin/ is mounted
│   ├── asgi.py / wsgi.py
│   └── .gitkeep
├── users/                       # Django app (empty scaffold)
│   ├── __init__.py  apps.py
│   └── migrations/__init__.py
├── chatbot/                     # Django app (empty scaffold)
│   ├── __init__.py  apps.py
│   └── migrations/
│       ├── __init__.py
│       └── 0001_initial.py      # preserved history — see §4
├── db.sqlite3                   # local dev database (git-ignored)
└── README.md
```

Each app is intentionally reduced to `__init__.py` + `apps.py` + `migrations/`.
That is the minimum Django needs to recognise an app — there are no `models.py`,
`views.py`, `urls.py`, `admin.py` or `tests.py`, and Django does not require any
of them (`AppConfig.import_models()` checks for the module before importing, and
admin autodiscovery fails silently on a missing `admin.py`).

## 2. What was removed

| File / directory | Why |
|---|---|
| `config/exceptions.py` | DRF error-envelope handler |
| `users/{serializers,views,urls,admin,models,tests}.py` | registration / login / current-user API |
| `chatbot/{serializers,views,urls,admin,models,models_corpus,tests}.py` | conversations, messages, health, corpus model |
| `chatbot/services/` | retrieval, generation, answer orchestration, ingestion |
| `chatbot/management/` | `ingest_chunks` command |

From `config/settings.py`: the `REST_FRAMEWORK`, `SPECTACULAR_SETTINGS`,
`CORS_*` / `CSRF_TRUSTED_ORIGINS` blocks, the `corsheaders` middleware and the
`rest_framework` / `authtoken` / `corsheaders` / `drf_spectacular` entries in
`INSTALLED_APPS`.

**Your database block in `settings.py` was left exactly as you wrote it**
(`DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT`).

## 3. Running it

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
cd backend
.venv\Scripts\python manage.py check          # should print: no issues
.venv\Scripts\python manage.py runserver      # http://127.0.0.1:8000/admin/
```

Dependencies kept (backend only): `Django==6.0.9`, `psycopg[binary]==3.3.6`,
`pgvector==0.5.1`, `python-dotenv>=1.0.0`. Everything the RAG code needs stays
in the root `requirements.txt` unchanged.

> `djangorestframework`, `django-cors-headers` and `drf-spectacular` were
> removed from `requirements.txt` because nothing imports them anymore. They may
> still be *installed* in `.venv` from the earlier pass; uninstall them yourself
> if you want the environment to mirror the file exactly:
> `pip uninstall djangorestframework django-cors-headers drf-spectacular`

## 4. Migrations and the database — read this before touching anything

* **No migration was deleted, created or run in this pass.**
* `chatbot/migrations/0001_initial.py` is preserved as-is. It creates
  `Conversation`, `Message`, `SourceDocument` and `DocumentChunk`, **but those
  models no longer exist in code.** That is the normal state of "kept history,
  removed features", and Django is fine with it — migrations are historical
  records and are never resolved against live model code.
* Consequence: **do not run `manage.py makemigrations`** until you have decided
  what to do with those four tables. It would correctly detect the missing
  models and emit `DeleteModel` operations, which would drop them on `migrate`.
* `manage.py migrate` was **not** run in this pass. `backend/db.sqlite3` is
  byte-for-byte untouched.
* If you later want a truly empty schema, do it deliberately — export or confirm
  the data first, then run `makemigrations` + `migrate` yourself.

## 5. Configuring Supabase later via `.env`

Settings read PostgreSQL credentials from environment variables (loaded by
`python-dotenv` from `<repo root>/.env`). A `.env` already exists locally in
this workspace (created 2026-10-26 20:46) — **do not delete it**. To rebuild it
from scratch:

```powershell
copy .env.example .env
```

Then fill in **four values together** — Django only switches to PostgreSQL when
`DB_NAME`, `DB_USER`, `DB_PASSWORD` *and* `DB_HOST` are all non-empty;
otherwise it falls back to local SQLite (development only, with a warning).

```dotenv
DJANGO_ENV=development
SECRET_KEY=                  # see .env.example for the generator command
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=postgres
DB_USER=postgres.abcdefghij
DB_PASSWORD=your-password-here
DB_HOST=aws-0.xx.pooler.supabase.com
DB_PORT=6543
```

How to derive those from Supabase: **Project Settings → Database → Connection
string (URI)**, which looks like
`postgres://postgres.abcdefghij:<PASSWORD>@aws-0.xx.pooler.supabase.com:6543/postgres`
— the part before `@` is `DB_USER` (+ `DB_NAME` from the path), the part between
`@` and `/` is `DB_HOST`. Use port **6543** for the pooler or **5432** for a
direct connection. `settings.py` already hardcodes `sslmode=require`, so no SSL
variable is needed.

* Production (`DJANGO_ENV=production`) **refuses to start** if `SECRET_KEY`,
  `ALLOWED_HOSTS` or the four `DB_*` values are missing — verified.
* **No connection has ever been established.** Nothing in this scaffold has been
  tested against a real PostgreSQL server or against Supabase, and no schema has
  been created there. `manage.py check --deploy` passing only proves the config
  is well-formed, not that the credentials work.
* `.env` is git-ignored (`.gitignore:19`), so it is **not** part of the
  repository even though it exists on disk — confirmed with
  `git check-ignore -v .env`. `.env.example` contains placeholders only, and no
  credential appears in any tracked file.

## 6. Verification performed

| Command | Result |
|---|---|
| `manage.py check` (with your real `.env`) | **no issues (0 silenced)**, exit 0 |
| `manage.py check --deploy` with `DJANGO_ENV=production` + `DB_*` | **no issues**, exit 0 |
| `manage.py check` with `DJANGO_ENV=production` and `DB_*` empty | **refuses to start** (`ImproperlyConfigured`), exit 1 |
| `manage.py test` | **Ran 0 tests**, exit 0 — no test database created |
| `rag/tests/test_rag_contract.py` | **19 tests OK**, exit 0 |
| `rag/tests/test_embeddings.py` | **29 tests OK**, exit 0 |
| `backend/db.sqlite3` SHA-256 before vs after | **identical** — database byte-for-byte untouched |
| `*.sqlite3` files in the repo | still exactly 1 (`backend/db.sqlite3`) — none created |

`manage.py check` does **not** open a database connection. Proven: it still
reports *no issues* when `DB_HOST` is forced to the deliberately unroutable
`host.invalid`, where any real connection attempt would fail. So passing checks
here say nothing about whether your Supabase credentials work — that remains
untested.

All RAG-side code (`rag/`, `core/`, `parsers/`, `pipeline/`) is untouched; its
newest file modification predates this session.

## 7. Where the previous implementation went

An earlier pass implemented the full API and is visible in this working tree as
deleted files (nothing has been committed — `git status` still shows
`## main...origin/main`). To inspect it: `git diff` / your editor's local
history. **No commit or push was made.**
