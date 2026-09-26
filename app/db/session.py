"""Database engine and session factory (synchronous SQLAlchemy 2.0 + psycopg 3).

Nothing here connects at import time. The engine is created by the application
factory from `Settings` and stored on `app.state`, which lets tests build an
app bound to the isolated test database without monkeypatching globals.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def build_engine(settings: Settings, *, url: str | None = None) -> Engine:
    return create_engine(
        url or settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            # Every session works in UTC, independent of the server's or host's time zone.
            "options": "-c TimeZone=UTC",
        },
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
