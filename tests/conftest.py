import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.exc import OperationalError

# Settings are read when app.main is imported, so the defaults must exist before any test
# module imports the app. Real values (CI, a local .env) take precedence.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://angi_reco:reco_dev@localhost:5432/angi")
os.environ.setdefault("RECO_API_KEY", "test-only-reco-api-key-0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "test")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_key() -> str:
    return os.environ["RECO_API_KEY"]


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """Database at the latest migration. Tests using it are skipped when no database is reachable,
    unless RECO_DB_TESTS=required (CI), where that is a failure."""
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 3})
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        engine.dispose()
        message = f"Database not reachable ({os.environ['DATABASE_URL']}): {exc.orig}"
        if os.environ.get("RECO_DB_TESTS") == "required":
            pytest.fail(message)
        pytest.skip(message)

    # No ini file: alembic.ini would reconfigure logging for the whole test run.
    config = Config()
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Connection]:
    """Connection inside a transaction that is rolled back after the test."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
