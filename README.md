# ANGI Recommendation Service

Personalized dish ranking for **ANGI (Ăn Gì)**, a capstone project that recommends Vietnamese regional dishes to travelers.

The service keeps a taste vector for every user and dish in schema `recommendation`, generates dish vectors with an LLM, learns from likes and dislikes, and ranks the candidate dishes the backend sends. It is internal: only [angi-backend](https://github.com/predtn/angi-backend) calls it.

| Repository | Role |
|---|---|
| [angi-frontend](https://github.com/Tulas2411/angi-frontend) | Next.js web app |
| [angi-backend](https://github.com/predtn/angi-backend) | ASP.NET Core API, schema `core`; calls this service |
| **angi-reco** (this repo) | FastAPI recommendation service, schema `recommendation` |

## Tech stack

| Concern | Technology |
|---|---|
| Runtime | Python 3.12+, FastAPI, uvicorn |
| Data | PostgreSQL 16 + pgvector, SQLAlchemy 2 (async, asyncpg), Alembic |
| Dish vectors | OpenAI-compatible LLM with structured output |
| Quality | ruff, pytest |

## Getting started

### Prerequisites

- Python 3.12+
- The local database of `angi-backend` running (`docker compose up -d --wait` in that repo). The service connects as role `angi_reco`, which owns only schema `recommendation`.

### Install and run

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # once; change the port or password if yours differ
alembic upgrade head               # create or update schema recommendation
uvicorn app.main:app --reload --port 8000
```

| URL | |
|---|---|
| `http://localhost:8000/health` | `{"status": "ok", "db": "ok", "active_config_version": 1}` |
| `http://localhost:8000/docs` | Interactive API reference (not served in production) |

Programs that call the service (the backend's `Recommendation:BaseUrl`, `scripts/backfill_dishes.py`) use `http://127.0.0.1:8000`, not `localhost`: uvicorn listens on IPv4 only, and Windows first tries `localhost` over IPv6, which takes about 2 s to fail, past the backend's 800 ms timeout.

## Configuration

Environment variables, or `.env` locally (never committed):

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | `postgresql://angi_reco:<password>@<host>:5432/angi`. The app uses asyncpg, Alembic and tests use psycopg; the driver in the URL is ignored |
| `RECO_API_KEY` | Shared with the backend (`Recommendation:ApiKey`), at least 32 characters |
| `LLM_API_KEY` | Provider key that generates dish vectors |
| `LLM_MODEL` | Model name; it must support structured output (JSON schema). Without `LLM_API_KEY` and `LLM_MODEL` the service starts, but dishes stay `pending` |
| `LLM_BASE_URL` | OpenAI endpoint; defaults to `https://api.openai.com/v1/` |
| `LLM_TIMEOUT_SECONDS` | Default `30` |
| `ENVIRONMENT` | `development`, `test` or `production` |
| `LOG_LEVEL` | Default `INFO` |

## API conventions

Endpoints RECO-01..09 are specified in the backend's API Design (sheet "Reco API (nội bộ)").

- Every endpoint except `/health` requires header `X-Api-Key`.
- JSON is snake_case and **not** wrapped in `ApiResponse`: a 2xx body is the DTO itself.
- Every error body is `{"error_code": "...", "message": "...", "errors": {...}}`; `errors` (field → messages) only for 422 `VALIDATION_FAILED`. The backend branches on `error_code`.
- The backend's outbox worker treats 4xx as final (dead) and 5xx as retryable, so return 503 (with `Retry-After`) for "try again later", never a 4xx.

Background jobs, feedback rules and switching the algorithm configuration: [runtime behavior](docs/runtime-behavior.md).

## Testing

```bash
ruff check .            # lint (ruff check --fix . fixes most issues)
ruff format --check .   # format (ruff format . rewrites the files)
pytest
```

Tests that need the database apply the migrations themselves and roll back what they write; without a reachable database they are skipped locally.

CI (`.github/workflows/ci.yml`) runs on every pull request and push to `dev` and `main`, on Python 3.12 with PostgreSQL 16 + pgvector: lint, format, migrations (apply, `alembic check`, roll back, apply again) and all tests, database tests included.

## Project structure

```text
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
scripts/             one-off tools (backfill of existing dishes)
tests/
docs/                design documents and guides (runtime behavior, migrations, deploy)
```

Adding an endpoint: request/response models in `app/schemas/`, the logic in `app/services/`, the route in `app/api/routes/`, then include its router in `protected_router`. Raise `AppError(status, error_code, message)` for expected errors. Schema changes go through Alembic: see [migrations](docs/migrations.md).

## Deployment

Production runs on Render as a Python web service with a single instance and worker, migrations applied by a pre-deploy step, and reco released before the backend. See [deploy](docs/deploy.md).

## Documentation

| Topic | Where |
|---|---|
| Algorithm, ontology, backend ↔ reco split | `docs/Recommendation_System_Design_Ver1.1.docx` |
| Survey questions and their vectors | [docs/Preference_Survey_Ver1.0.md](docs/Preference_Survey_Ver1.0.md) |
| Conversation taste vectors, Agent impressions | [docs/Conversation_Preferences_Ver1.0.md](docs/Conversation_Preferences_Ver1.0.md) |
| Endpoints RECO-01..09 | `angi-backend/docs/ANGI_API_Design_Ver*.xlsx`, sheet "Reco API (nội bộ)" |
| Tables and columns | `angi-backend/docs/ANGI_Data_Dictionary_Ver*.xlsx`, sheet "Recommendation" |
| Runtime behavior | [docs/runtime-behavior.md](docs/runtime-behavior.md) |
| Migrations | [docs/migrations.md](docs/migrations.md) |
| Deploy (Render) | [docs/deploy.md](docs/deploy.md) |

## Contributing

Branches, commit messages and pull requests follow `angi-backend/.agents/commit_guide.md`. Open pull requests against `dev`; a pull request is merged only when the `lint-test` check is green.

## License

[MIT](LICENSE)
