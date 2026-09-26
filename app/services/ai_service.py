"""AI assistant service (Stage 7): runs the LangGraph workflow and audits every request.

Audit (`ai.analysis`): SUCCESS when a validated analysis is returned, FAILURE when the assistant
abstains, DENIED when the request is refused or unauthorized. Details hold only metadata
(analysis type, status, reason, tools, evidence/citation ids, guardrail flags, model, latency,
question length and SHA-256) - never the question text, the evidence or the model output.
"""

import hashlib
import time

from sqlalchemy.orm import Session

from app.ai.graph import AnalysisDenied, build_graph, open_read_only_session
from app.ai.providers import AIUnavailableError, ModelFactory
from app.ai.schemas import (
    AIAnalysisRequest,
    AIAnalysisResult,
    AICapabilities,
    AIModelInfo,
    AIToolInfo,
    AnalysisStatus,
    AnalysisType,
)
from app.ai.tools import TOOL_SPECS
from app.core.audit import AuditRecorder
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.principal import Principal
from app.models.audit import AuditOutcome

OUTCOME = {AnalysisStatus.COMPLETED: AuditOutcome.SUCCESS, AnalysisStatus.ABSTAINED: AuditOutcome.FAILURE,
           AnalysisStatus.REFUSED: AuditOutcome.DENIED}


class AIServiceUnavailable(RuntimeError):
    pass


class AIService:
    def __init__(self, session: Session, settings: Settings, model_factory: ModelFactory) -> None:
        self._session = session
        self._settings = settings
        self._model_factory = model_factory
        self._audit = AuditRecorder(session.get_bind())

    def capabilities(self, principal: Principal, enabled: bool) -> AICapabilities:
        return AICapabilities(
            enabled=enabled, provider=self._settings.llm_provider, model=self._settings.llm_model,
            analysis_types=list(AnalysisType),
            tools=[AIToolInfo(name=s.name, description=s.description, required_permission=s.permission.value,
                              read_only=True, available_to_you=principal.has(s.permission)) for s in TOOL_SPECS],
        )

    def analyze(self, principal: Principal, request: AIAnalysisRequest, request_id: str) -> AIAnalysisResult:
        started = time.perf_counter()
        try:
            model = self._model_factory()
        except AIUnavailableError as exc:
            self._record(principal, request, AuditOutcome.FAILURE, {"status": "UNAVAILABLE", "reason": str(exc)}, started)
            raise AIServiceUnavailable("The AI assistant is not configured.") from None

        read_only = open_read_only_session(self._session)
        try:
            graph = build_graph(session=self._session, read_only_session=read_only, model=model,
                                items_per_tool=self._settings.ai_max_items_per_tool)
            state = graph.invoke({"principal": principal, "patient_id": request.patient_id,
                                  "analysis_type": request.analysis_type, "question": request.question,
                                  "requested_tools": request.tools})
        except AnalysisDenied as denied:
            self._record(principal, request, AuditOutcome.DENIED,
                         {"status": "DENIED", "reason_code": denied.reason_code}, started)
            if denied.http_status == 404:
                raise NotFoundError(denied.message) from None
            raise PermissionDeniedError(denied.message) from None
        finally:
            read_only.rollback()
            read_only.close()

        output = state.get("output")
        result = AIAnalysisResult(
            request_id=request_id,
            status=state["status"],
            reason_code=state.get("reason_code"),
            message=state["message"],
            patient_id=request.patient_id,
            patient_number=state.get("patient_number"),
            analysis_type=request.analysis_type,
            output=output if state["status"] == AnalysisStatus.COMPLETED or (
                output is not None and output.status == "ABSTAIN") else None,
            tools_used=state.get("tools_used", []),
            tools_withheld=state.get("tools_withheld", []),
            evidence_count=len(state.get("evidence", [])),
            model=AIModelInfo(provider=self._settings.llm_provider, model=self._settings.llm_model),
            generated_at=utc_now(),
        )
        self._record(principal, request, OUTCOME[result.status], {
            "status": result.status.value,
            "reason_code": result.reason_code,
            "tools_used": result.tools_used,
            "tools_withheld": result.tools_withheld,
            "evidence_count": result.evidence_count,
            "cited_sources": [c.source_id for c in output.evidence] if output else [],
            "guardrail_flags": state.get("guardrail_flags", []),
            "model_latency_ms": state.get("model_latency_ms"),
        }, started)
        return result

    def _record(self, principal: Principal, request: AIAnalysisRequest, outcome: AuditOutcome, details: dict,
                started: float) -> None:
        question = request.question or ""
        self._audit.record(
            "ai.analysis", outcome, principal=principal,
            resource_type="patients", resource_id=request.patient_id, patient_id=request.patient_id,
            details={**details, "analysis_type": request.analysis_type.value,
                     "provider": self._settings.llm_provider, "model": self._settings.llm_model,
                     "question_length": len(question),
                     "question_sha256": hashlib.sha256(question.encode()).hexdigest() if question else None,
                     "requested_tools": request.tools, "latency_ms": round((time.perf_counter() - started) * 1000)},
        )


__all__ = ["AIService", "AIServiceUnavailable"]
