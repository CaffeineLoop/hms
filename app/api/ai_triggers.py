"""Configured event triggers for the four-day risk analysis (Stage 8).

No new event architecture: a clinical write endpoint that is configured as a trigger
(AI_RISK_EVENT_TRIGGERS, e.g. "observation.created") schedules the analysis with FastAPI's
built-in BackgroundTasks after its own transaction has committed. The analysis runs through the
same LangGraph workflow, guardrails, authorization and audit as a manual request, as the SAME
authenticated user who made the clinical write. Staff-less principals and users without
`ai.analysis` never trigger it (no system identity, no RBAC bypass).
"""

import uuid

from fastapi import BackgroundTasks, Request

from app.api.routes.ai import current_request_id
from app.core.permissions import P
from app.core.principal import Principal
from app.services.ai_service import run_event_risk_analysis


def maybe_schedule_risk_analysis(request: Request, background: BackgroundTasks, principal: Principal, event: str,
                                 patient_id: uuid.UUID, source_id: uuid.UUID) -> bool:
    settings = request.app.state.settings
    if event not in settings.risk_triggers:
        return False
    if principal.user_id is None or principal.staff_id is None or not principal.has(P.AI_ANALYSIS):
        return False
    background.add_task(run_event_risk_analysis, request.app.state.session_factory, settings,
                        request.app.state.ai_model_factory, principal, patient_id, source_id,
                        current_request_id(), event)
    return True
