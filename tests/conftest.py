import os

import pytest

# Settings are read when app.main is imported, so the defaults must exist before any test
# module imports the app. Real values (CI, a local .env) take precedence.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://angi_reco:reco_dev@localhost:5432/angi")
os.environ.setdefault("RECO_API_KEY", "test-only-reco-api-key-0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def api_key() -> str:
    return os.environ["RECO_API_KEY"]
