from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, func
from sqlalchemy.orm import MappedColumn, mapped_column

from app.core.ontology import DIMENSION_COUNT


def ontology_vector() -> VECTOR:
    return VECTOR(DIMENSION_COUNT)


def created_at() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
