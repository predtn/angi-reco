# angi-reco

Recommendation service (FastAPI) for the ANGI capstone project. It scores the candidate dishes the backend sends and keeps the user and dish vectors in schema `recommendation`.

| Source | Covers |
|---|---|
| `.docs/Recommendation_System_Design_Ver1.1.docx` | Algorithm, ontology, backend ↔ reco split |
| `angi-backend/.docs/ANGI_API_Design_Ver1.8.xlsx`, sheet "Reco API (nội bộ)" | Endpoints RECO-01..09 |
| `angi-backend/.docs/ANGI_Data_Dictionary_Ver1.2.xlsx`, sheet "Recommendation" | Tables and columns |
| `angi-backend/.agents/commit_guide.md` | Branches, commits, pull requests |

## Setup

Requires Python 3.12+ and the database of `angi-backend` (`docker compose up -d --wait` in that repo). The service connects as role `angi_reco`, which owns only schema `recommendation`.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # once; change the port or password if yours differ
alembic upgrade head               # create or update schema recommendation
uvicorn app.main:app --reload --port 8000
```

- `GET http://localhost:8000/health` → `{"status": "ok", "db": "ok", "active_config_version": 1}`
- API docs: http://localhost:8000/docs (not served in production)

### Configuration

Environment variables, or `.env` locally (never committed):

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | `postgresql://angi_reco:<password>@<host>:5432/angi`. The app uses asyncpg, Alembic and tests use psycopg; the driver in the URL is ignored |
| `RECO_API_KEY` | Shared with the backend (`Recommendation:ApiKey`), at least 32 characters |
| `LLM_API_KEY` | LLM that generates dish vectors |
| `ENVIRONMENT` | `development`, `test` or `production` |
| `LOG_LEVEL` | Default `INFO` |

## How the API behaves

- Every endpoint except `/health` requires header `X-Api-Key`.
- JSON is snake_case and **not** wrapped in `ApiResponse`: a 2xx body is the DTO itself.
- Every error body is `{"error_code": "...", "message": "...", "errors": {...}}`; `errors` (field → messages) only for 422 `VALIDATION_FAILED`. The backend branches on `error_code`.
- The outbox worker treats 4xx as final (dead) and 5xx as retryable, so return 503 (with `Retry-After`) for "try again later", never a 4xx.

## Project layout

```
app/
  main.py            create_app(), lifespan (database engine; background jobs start here)
  core/              settings, errors, X-Api-Key, ontology (12 dimensions, fixed order)
  db/                declarative base (schema recommendation, constraint naming), async session
  models/            one ORM class per table
  schemas/           request / response models
  api/router.py      public_router (/health) and protected_router (everything else)
  api/routes/        one module per endpoint group
alembic/versions/    migrations
tests/
```

Adding an endpoint: request/response models in `app/schemas/`, the route in `app/api/routes/`, then include its router in `protected_router`. Raise `AppError(status, error_code, message)` for expected errors.

## Migrations

Schema `recommendation` changes only through Alembic (`commit_guide.md` §10).

```bash
# after changing app/models (pull dev first)
alembic revision --autogenerate --rev-id 0002 -m "add something"
# review the file, then
alembic upgrade head
alembic check            # must print "No new upgrade operations detected."
```

- Number revisions in order (`0002`, `0003`, ...). If two pull requests create the same number, the one merged second regenerates its revision on the new head.
- Autogenerate does not see data, raw SQL or extensions: seed rows and `CREATE EXTENSION` are written by hand (see `0001`).
- `vector` must already exist in schema `public`, because role `angi_reco` cannot create extensions. The backend's init script installs it locally; on Render it is created once with the database's admin user when the environment is set up.

## Tests and CI

```bash
ruff check .            # lint (ruff check --fix . fixes most issues)
ruff format --check .   # format (ruff format . rewrites the files)
pytest
```

Tests that need the database apply the migrations themselves and roll back what they write. Without a reachable database they are skipped locally.

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and push to `dev` and `main`, on Python 3.12 with PostgreSQL 16 + pgvector: lint, format, migrations (apply, `alembic check`, roll back, apply again) and all tests, database tests included. A pull request can be merged only when the `lint-test` check is green.
