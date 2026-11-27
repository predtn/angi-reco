# Deploy (self-hosted, Docker Compose)

Production runs on one Linux server with Docker Compose. Reco is the service `angi-reco` in the same Compose project (`angi`) as Postgres, the backend and the frontend, defined in a second file, `~/angi/docker-compose.reco.yml`. Nothing in the repo is host-specific: the image recipe below is the whole contract.

## Topology

```
angi-frontend ─▶ angi-backend ─X-Api-Key─▶ angi-reco:8000 ─▶ angi-postgres:5432 (schema recommendation, role angi_reco)
```

- Reco has no public hostname and publishes no host port. Only the backend calls it, by service name on the network `angi_default`.
- No CD: GitHub Actions runs CI only, releases are manual (see [Update](#update)).

## `docker-compose.reco.yml`

The repo has no Dockerfile; the image is built with `dockerfile_inline`. `RECO_REPO_PATH` (in `~/angi/.env`) is the absolute path of this repo's clone on the server, e.g. `/home/<user>/angi/angi-reco`.

```yaml
services:
  angi-reco:
    image: angi-reco:local
    build:
      context: ${RECO_REPO_PATH:?Set RECO_REPO_PATH to the angi-reco checkout on the server}
      dockerfile_inline: |
        FROM python:3.12-slim
        ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
        WORKDIR /app
        COPY pyproject.toml ./
        COPY app ./app
        RUN pip install .
        COPY alembic.ini ./
        COPY alembic ./alembic
        COPY scripts ./scripts
        RUN useradd --system --uid 10001 reco && chown -R reco /app
        USER reco
        EXPOSE 8000
        # 1 worker: the two background loops must run once.
        CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
    restart: unless-stopped
    env_file: reco.env
    depends_on:
      angi-postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
```

| Point | Why |
|---|---|
| Migrations at start | `alembic upgrade head` (schema `recommendation`) runs every time the container starts, before `uvicorn`. It reads the same environment as the service, so `RECO_API_KEY` must already be set |
| **1 container, 1 worker** | Two background loops run inside the process (dish vectors every 5 minutes, 30-day log retention every hour); more workers or containers would run them twice |
| `restart: unless-stopped`, always on | The backend waits 800 ms for a ranking (3 s for the assistant), so while reco is down or starting, requests fall back to the backend's order by rating, which is not personalized |
| Health check | `/health` (RECO-07): 200 with the active algorithm config when PostgreSQL answers; no `X-Api-Key` |

### Two Compose files

`angi-reco` lives in the second file. Every command that touches it reads both files:

```bash
cd ~/angi
docker compose -f compose.yaml -f docker-compose.reco.yml <command> angi-reco
```

A plain `docker compose …` reads only `compose.yaml` and warns `Found orphan containers (angi-angi-reco-1)`. **Never add `--remove-orphans`**: it deletes the reco container. To drop the `-f` flags, add `COMPOSE_FILE=compose.yaml:docker-compose.reco.yml` to `~/angi/.env`; `docker compose config --services` must then list four services.

## Environment variables (`~/angi/reco.env`)

The values in `.env.example` are for a local database only. The file holds secrets: `chmod 600`, never committed.

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` (hides `/docs` and the OpenAPI schema) |
| `DATABASE_URL` | `postgresql://angi_reco:<ANGI_RECO_DB_PASSWORD>@angi-postgres:5432/angi` (owns only schema `recommendation`) |
| `RECO_API_KEY` | At least 32 random characters; the **same** value as the backend's `Recommendation__ApiKey`. The service refuses to start with a shorter key |
| `LLM_API_KEY`, `LLM_MODEL` | The provider key and a model with structured output. Without both the service starts, but new dishes stay `pending` (no vector, so they are ranked without taste) |
| `LLM_BASE_URL` | `https://api.openai.com/v1/`, or another OpenAI-compatible provider |
| `LOG_LEVEL` | `INFO` |

The backend side: `Recommendation__BaseUrl=http://angi-reco:8000` and `Recommendation__ApiKey` in `backend.env`.

## Database, once

The Postgres container runs `angi-backend/docker/postgres/init/01-roles-schemas.sh` on its first start with an empty volume: it creates role `angi_reco` with schema `recommendation` and the extension `vector` in `public` (role `angi_reco` cannot create extensions). Its password comes from `ANGI_RECO_DB_PASSWORD` in `~/angi/.env` and must match `DATABASE_URL`.

## Release order

When a release changes several services: reco first (its migration runs when the container starts), then the backend (its `./efbundle`, then the API), then the frontend. Reco only adds tables and columns ahead of the backend, so an older backend keeps working against a newer reco.

## Update

```bash
cd ~/angi
git -C angi-reco pull
docker compose -f compose.yaml -f docker-compose.reco.yml build angi-reco
docker compose -f compose.yaml -f docker-compose.reco.yml up -d --force-recreate angi-reco
docker compose -f compose.yaml -f docker-compose.reco.yml ps angi-reco   # (healthy), IMAGE angi-reco:local
```

Build one service at a time (the server has 8 GB RAM). A changed `reco.env` only needs the `up -d --force-recreate` line. If `ps` shows an `sha256:…` image, the new image was built but the old container is still running: recreate it.

## After a deploy

The image of the frontend has `wget`, so internal checks run from there:

```bash
docker compose exec angi-frontend wget -qO- http://angi-reco:8000/health; echo   # {"status": "ok", "db": "ok", ...}
docker compose exec angi-frontend wget -qO- -S http://angi-reco:8000/docs 2>&1 | head -1   # 404 in production
docker compose -f compose.yaml -f docker-compose.reco.yml logs --tail=50 angi-reco
```
