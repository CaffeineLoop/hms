"""API contracts for the health endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    environment: str


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["reachable", "unreachable"]
    latency_ms: float | None = None
    migration_revision: str | None = None
