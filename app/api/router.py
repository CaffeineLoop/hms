"""Aggregates every API router. Domain routers are added here in later stages."""

from fastapi import APIRouter

from app.api.routes import access, audit, auth, clinical, diagnostics, health, patients, staff, workflow

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(access.router)
api_router.include_router(audit.router)
api_router.include_router(patients.router)
api_router.include_router(clinical.router)
api_router.include_router(diagnostics.router)
api_router.include_router(staff.router)
api_router.include_router(workflow.router)
