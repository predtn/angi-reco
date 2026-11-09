# Deploy (Render)

The service runs as a Render **Web Service**, **Python** runtime, root directory `angi-reco`, in the same region as the backend and the database. Nothing in the repo is Render-specific: the commands below are the whole contract.

## Render settings

| Setting | Value |
|---|---|
| Build Command | `pip install .` |
| Pre-Deploy Command | `alembic upgrade head` (schema `recommendation`; it reads the same environment as the service, so `RECO_API_KEY` must already be set) |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health Check Path | `/health` (RECO-07: 200 with the active algorithm config when PostgreSQL answers; no `X-Api-Key`) |
| Instances | **1**, with a single worker. Two background loops run inside the process (dish vectors every 5 minutes, 30-day log retention every hour); more workers or instances would run them twice. |
| Instance type | One that never sleeps. The backend waits 800 ms for a ranking (3 s for the assistant), so after a cold start the first requests fall back to the backend's order by rating, which is not personalized. |

## Environment variables

Render → Environment. The values in `.env.example` are for a local database only.

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` (hides `/docs` and the OpenAPI schema) |
| `DATABASE_URL` | The production database as role `angi_reco` (owns only schema `recommendation`) |
| `RECO_API_KEY` | At least 32 random characters; the **same** value as the backend's `Recommendation__ApiKey`. The service refuses to start with a shorter key |
| `LLM_API_KEY`, `LLM_MODEL` | The provider key and a model with structured output. Without both the service starts, but new dishes stay `pending` (no vector, so they are ranked without taste) |
| `LLM_BASE_URL` | Only for a provider other than OpenAI |
| `LOG_LEVEL` | `INFO` |
| `PYTHON_VERSION` | `3.12.x` (Render's default can be another version; the project requires 3.12+) |

## Database, once

Before the first deploy (as the database owner or superuser): `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;` (role `angi_reco` cannot create extensions), then create role `angi_reco` and give it schema `recommendation`, as `angi-backend/docker/postgres/init/01-roles-schemas.sh` does locally.

## Release order

When a release changes both services: reco first (its migration, then the service), then the backend (its `./efbundle`, then the API), then the frontend. Reco only adds tables and columns ahead of the backend, so an older backend keeps working against a newer reco.

## Backend → reco address

The backend reaches reco through `Recommendation__BaseUrl`: prefer Render's internal address of this service (`http://<service-name>:<port>`, same region) over the public `onrender.com` URL, so the calls stay inside Render's network. Every endpoint except `/health` still checks `X-Api-Key`.

## After a deploy

```bash
curl https://<reco-host>/health                                  # 200 {"status": "ok", "db": "ok", ...}
curl -s -o /dev/null -w "%{http_code}\n" https://<reco-host>/docs  # 404 in production
```
