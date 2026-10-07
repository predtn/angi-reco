from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db.base import SCHEMA, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, _: dict) -> bool:
    # Role angi_reco only owns schema recommendation; ignore everything else (core, public).
    if type_ == "schema":
        return name == SCHEMA
    return True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=get_settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Same URL as the app; postgresql+psycopg works with both the async and the sync engine.
    # Role angi_reco defaults to search_path = recommendation, which autogenerate would treat as
    # the unnamed default schema and skip. Every name in the migrations is schema-qualified.
    engine = create_engine(
        get_settings().database_url,
        poolclass=pool.NullPool,
        connect_args={"options": "-c search_path=public"},
    )
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
