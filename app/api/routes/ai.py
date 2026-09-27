"""AI assistant endpoints (Stages 7-8). Read-only clinical analysis; permission `ai.analysis`.

    GET  /api/ai/capabilities                      provider/model, analysis types, read-only tool allowlist
    POST /api/ai/analyses                          run a bounded analysis for one patient
                                                   (analysis_type FOUR_DAY_RISK: potential risk signals
                                                   for the next 4 days, stored for human review)
    GET  /api/ai/risk-analyses                     stored risk analyses (ai.analysis or ai.review)
    GET  /api/ai/risk-analyses/{id}                one stored risk analysis
    POST /api/ai/risk-analyses/{id}/review         acknowledge / dismiss (ai.review) - AI record only

Outcomes: 200 with status COMPLETED / ABSTAINED / REFUSED; 403 (no permission, staff-less
principal, patient out of scope); 404 (unknown patient / analysis); 409 (already reviewed);
503 (assistant not configured).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.ai.providers import model_is_configured
from app.ai.schemas import (
    AIAnalysisRequest,
    AIAnalysisResult,
    AICapabilities,
    RiskAnalysisListParams,
    RiskAnalysisRead,
    RiskReviewCreate,
)
from app.api.auth import requires, requires_any
from app.core.audit import request_context
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.services.ai_service import AIService

router = APIRouter(prefix="/api/ai", tags=["ai assistant"])

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Missing ai.analysis, staff-less principal, or patient out of scope"},
    404: {"description": "Patient not found"},
    503: {"description": "AI assistant not configured"},
}
_REVIEW_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Missing permission, staff-less principal, or patients out of scope"},
    404: {"description": "Risk analysis not found"},
    409: {"description": "Already reviewed"},
}
Caller = Annotated[Principal, requires(P.AI_ANALYSIS)]
Viewer = Annotated[Principal, requires_any(P.AI_ANALYSIS, P.AI_REVIEW)]
Reviewer = Annotated[Principal, requires(P.AI_REVIEW)]


def _service(request: Request, session: Session = Depends(get_db)) -> AIService:
    return AIService(session, request.app.state.settings, request.app.state.ai_model_factory)


Service = Annotated[AIService, Depends(_service)]


def current_request_id() -> str:
    return getattr(request_context.get(), "request_id", None) or "unknown"


@router.get("/capabilities", response_model=AICapabilities, responses=_ERRORS)
def capabilities(request: Request, principal: Caller, service: Service):
    return service.capabilities(principal, enabled=model_is_configured(request.app.state.settings))


@router.post("/analyses", response_model=AIAnalysisResult, responses=_ERRORS)
def analyze(data: AIAnalysisRequest, principal: Caller, service: Service):
    return service.analyze(principal, data, current_request_id())


@router.get("/risk-analyses", response_model=Page[RiskAnalysisRead], responses=_REVIEW_ERRORS)
def list_risk_analyses(params: Annotated[RiskAnalysisListParams, Query()], principal: Viewer, service: Service):
    items, total = service.list_risk_analyses(principal, params)
    return Page[RiskAnalysisRead](items=[RiskAnalysisRead.model_validate(i) for i in items], total=total,
                                  limit=params.limit, offset=params.offset)


@router.get("/risk-analyses/{analysis_id}", response_model=RiskAnalysisRead, responses=_REVIEW_ERRORS)
def get_risk_analysis(analysis_id: uuid.UUID, principal: Viewer, service: Service):
    return service.get_risk_analysis(principal, analysis_id)


@router.post("/risk-analyses/{analysis_id}/review", response_model=RiskAnalysisRead, responses=_REVIEW_ERRORS)
def review_risk_analysis(analysis_id: uuid.UUID, data: RiskReviewCreate, principal: Reviewer, service: Service):
    return service.review_risk_analysis(principal, analysis_id, data)
