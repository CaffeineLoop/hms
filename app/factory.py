"""Application factory.

Kept separate from app/main.py so that importing the factory (e.g. from tests)
does not build the module-level app from the process environment.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.ai.providers import build_model_factory
from app.api.errors import register_exception_handlers
from app.api.middleware import install_middleware
from app.api.router import api_router
from app.core.clock import configure_facility_timezone
from app.core.config import Environment, Settings, get_settings
from app.db.session import build_engine, build_session_factory


class RedactQueryStringFilter(logging.Filter):
    """Stage 6: uvicorn's access log records the full path including the query string, which
    can carry patient data (e.g. /api/patients?q=<name>). Keep only the path."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            args[2] = args[2].split("?", 1)[0]
            record.args = tuple(args)
        return True


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level.upper())
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactQueryStringFilter) for f in access.filters):
        access.addFilter(RedactQueryStringFilter())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Tests pass their own Settings to bind the test database."""
    settings = settings or get_settings()
    configure_logging(settings)
    configure_facility_timezone(settings.app_timezone)

    # create_engine() does not connect; the first connection is made on first use.
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    # Stage 6: no interactive docs / schema in production (reduces the exposed surface).
    production = settings.app_env == Environment.PRODUCTION
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if production else {}
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan, debug=False, **docs)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.ai_model_factory = build_model_factory(settings)  # Stage 7: configurable LLM provider
    app.include_router(api_router)
    register_exception_handlers(app)
    install_middleware(app)
    return app
