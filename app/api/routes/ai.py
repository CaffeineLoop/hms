"""AI assistant endpoints (Stage 7). Read-only clinical analysis; permission `ai.analysis`.

    GET  /api/ai/capabilities   provider/model, analysis types and the read-only tool allowlist
    POST /api/ai/analyses       run a bounded analysis for one patient

Outcomes: 200 with status COMPLETED / ABSTAINED / REFUSED; 403 (no permission, staff-less
principal, patient out of scope); 404 (unknown patient); 503 (assistant not configured).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.providers import model_is_configured
from app.ai.schemas import AIAnalysisRequest, AIAnalysisResult, AICapabilities
from app.api.auth import requires
from app.core.audit import request_context
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.services.ai_service import AIService

router = APIRouter(prefix="/api/ai", tags=["ai assistant"])

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Missing ai.analysis, staff-less principal, or patient out of scope"},
    404: {"description": "Patient not found"},
    503: {"description": "AI assistant not configured"},
}
Caller = Annotated[Principal, requires(P.AI_ANALYSIS)]


def _service(request: Request, session: Session = Depends(get_db)) -> AIService:
    return AIService(session, request.app.state.settings, request.app.state.ai_model_factory)


Service = Annotated[AIService, Depends(_service)]


@router.get("/capabilities", response_model=AICapabilities, responses=_ERRORS)
def capabilities(request: Request, principal: Caller, service: Service):
    return service.capabilities(principal, enabled=model_is_configured(request.app.state.settings))


@router.post("/analyses", response_model=AIAnalysisResult, responses=_ERRORS)
def analyze(data: AIAnalysisRequest, principal: Caller, service: Service):
    request_id = getattr(request_context.get(), "request_id", None) or "unknown"
    return service.analyze(principal, data, request_id)
