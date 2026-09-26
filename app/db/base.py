"""SQLAlchemy declarative base shared by every ORM model.

`Base.metadata` is the single source of schema truth that Alembic compares
against the database. A naming convention is set so that constraints and
indexes get deterministic names — without it, Alembic cannot reliably drop or
alter unnamed constraints in later migrations.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
