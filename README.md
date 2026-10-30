# angi-reco

Recommendation service (FastAPI) for the ANGI capstone project. It scores the candidate dishes the backend sends and keeps the user and dish vectors in schema `recommendation`.

| Source | Covers |
|---|---|
| `.docs/Recommendation_System_Design_Ver1.1.docx` | Algorithm, ontology, backend ↔ reco split |
| `.docs/Preference_Survey_Ver1.0.md` | Survey questions, `option_code`s and their vectors (`survey_option_vectors`) |
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
- Programs that call the service (the backend's `Recommendation:BaseUrl`, `scripts/backfill_dishes.py`) use `http://127.0.0.1:8000`, not `localhost`: uvicorn listens on IPv4 only, and Windows first tries `localhost` over IPv6, which takes about 2 s to fail, past the backend's 800 ms timeout.

### Configuration

Environment variables, or `.env` locally (never committed):

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | `postgresql://angi_reco:<password>@<host>:5432/angi`. The app uses asyncpg, Alembic and tests use psycopg; the driver in the URL is ignored |
| `RECO_API_KEY` | Shared with the backend (`Recommendation:ApiKey`), at least 32 characters |
| `LLM_API_KEY` | Provider key that generates dish vectors |
| `LLM_MODEL` | Model name; it must support structured output (JSON schema). Without `LLM_API_KEY` and `LLM_MODEL` the service starts, but dishes stay `pending` |
| `LLM_BASE_URL` | OpenAI-compatible endpoint; defaults to `https://api.openai.com/v1/`. For Gemini use `https://generativelanguage.googleapis.com/v1beta/openai/` with a Gemini key and model |
| `LLM_TIMEOUT_SECONDS` | Default `30` |
| `ENVIRONMENT` | `development`, `test` or `production` |
| `LOG_LEVEL` | Default `INFO` |

## How the API behaves

- Every endpoint except `/health` requires header `X-Api-Key`.
- JSON is snake_case and **not** wrapped in `ApiResponse`: a 2xx body is the DTO itself.
- Every error body is `{"error_code": "...", "message": "...", "errors": {...}}`; `errors` (field → messages) only for 422 `VALIDATION_FAILED`. The backend branches on `error_code`.
- The outbox worker treats 4xx as final (dead) and 5xx as retryable, so return 503 (with `Retry-After`) for "try again later", never a 4xx.

### Dish vectors

RECO-01 answers at once with the dish `pending`; its vector is generated right after in a background task. A loop started with the app retries `pending` / `failed` dishes every 5 minutes, at most 5 times per content (`attempt_count`), so a dish still `failed` after 5 tries keeps its `last_error` for inspection (Design §2.4).

The backend's outbox worker sends every dish change from then on. Dishes that were already in `core.dishes` before reco first ran can be sent once with the backfill script (rerunning is harmless):

```bash
python scripts/backfill_dishes.py --core-database-url postgresql://angi_backend:backend_dev@localhost:5432/angi --reco-url http://127.0.0.1:8000
```

The script is the only code that reads schema `core`, with the backend role; the service never does.

### Feedback

RECO-04 (`POST /feedback`, sent by the outbox worker for each like / dislike) applies Design §5.2 in one transaction that locks the user's row:

- A known `event_uuid` answers `duplicate` and changes nothing, also when the same event arrives twice at once.
- A dish reco never received is 404 `DISH_NOT_FOUND` (the worker marks the event dead). A dish whose vector is `pending` or `failed` is 503 `DISH_VECTOR_NOT_READY` with `Retry-After: 60`, so the worker retries; the user's later events wait behind it. A deactivated dish that has a vector still counts.
- `occurred_at` needs a time zone: the latest `occurred_at` is the vote counted in `dish_stats`. An older event that arrives late still adds to r, n, the user vector and m.

### Algorithm configuration

Every recommendation uses the one row of `algorithm_configs` with `is_active = true` and logs its `config_version`. Migrations add configurations; they never switch the active one silently.

| `config_version` | Parameters | State |
|---|---|---|
| 1 | Design §3.5, γ = 0 (no exploration) | active |
| 2 | same as 1, γ = 0.1 (UCB, Design §3.4) | added inactive (migration 0003) |

UCB only changes the ranking once the app reports impressions (IMP-01 → RECO-06): until then N_total = 0 and every Exploration score is 0. Switch versions in one transaction, the old one off first (the unique index on `is_active` is checked row by row):

```sql
BEGIN;
UPDATE recommendation.algorithm_configs SET is_active = false WHERE is_active;
UPDATE recommendation.algorithm_configs SET is_active = true WHERE config_version = 2;  -- 1 to go back
COMMIT;
```

The backend caches a ranked DISH-01 list for 30 minutes, so lists ranked with the previous version can still be paged for that long.

## Project layout

```
app/
  main.py            create_app(), lifespan (database engine; background jobs start here)
  core/              settings, errors, X-Api-Key, ontology (12 dimensions, fixed order; scores → vector)
  db/                declarative base (schema recommendation, constraint naming), async session
  models/            one ORM class per table
  schemas/           request / response models
  services/          the work behind each endpoint (routes stay thin)
  api/router.py      public_router (/health) and protected_router (everything else)
  api/routes/        one module per endpoint group
alembic/versions/    migrations
tests/
```

Adding an endpoint: request/response models in `app/schemas/`, the logic in `app/services/`, the route in `app/api/routes/`, then include its router in `protected_router`. Raise `AppError(status, error_code, message)` for expected errors.

## Migrations

Conversation taste vectors and commit-only Agent impressions are documented in
[Conversation Preferences v1](.docs/Conversation_Preferences_Ver1.0.md).
Deploy reco migration `0004` and this service before the matching backend migration/service.
Existing recommendation requests continue to use the long-term profile by default.

Schema `recommendation` changes only through Alembic (`commit_guide.md` §4).

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
