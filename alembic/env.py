"""Alembic migration environment for the HMS.

How it is connected to SQLAlchemy:
- `target_metadata` is `app.models.Base.metadata`. Importing `app.models`
  registers every ORM model on that metadata, so `alembic revision
  --autogenerate` diffs the real models against the real database.
- The database URL comes from the application Settings (DATABASE_URL), never
  from alembic.ini. Programmatic callers (the test suite) may instead pass
  `config.attributes["database_url"]` to target another database, such as
  the isolated test database.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.attributes.get("database_url")
    if override:
        return override
    return get_settings().database_url.get_secret_value()


def _configure_kwargs() -> dict:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (alembic upgrade --sql)."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, **_configure_kwargs())
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
