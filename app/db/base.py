from enum import StrEnum

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "recommendation"

# Same constraint names as the backend's EF conventions (pk_, fk_, ix_, ck_ + snake_case).
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(referred_table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


def in_check(column: str, values: type[StrEnum]) -> str:
    """CHECK body allowing only the values of a StrEnum, e.g. "status IN ('pending', 'ready')"."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


def not_zero_vector(column: str) -> str:
    # Cosine distance with a zero vector is NaN (Design §4.2): store NULL instead.
    return f"{column} IS NULL OR vector_norm({column}) > 0"
