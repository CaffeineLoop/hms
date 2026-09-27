"""AI assistant service (Stages 7-8): runs the LangGraph workflow and audits every request.

Audit (`ai.analysis`): SUCCESS when a validated analysis is returned, FAILURE when the assistant
abstains, DENIED when the request is refused or unauthorized. Details hold only metadata
(analysis type, status, reason, tools, evidence/citation ids, guardrail flags, model, latency,
question length and SHA-256) - never the question text, the evidence or the model output.

Stage 8 (FOUR_DAY_RISK):
- the service fixes the reference time (request value or now) before the graph runs; the horizon
  is always reference_at .. reference_at + 4 days;
- every analysis that got past authorization and the input guardrails (COMPLETED or ABSTAINED)
  is stored in `ai_risk_analyses` as PENDING_REVIEW - the AI review pathway. The graph itself
  still writes nothing; this service writes only that AI-suggestion table, never clinical records;
- review (`ai.review`): a staff-linked user acknowledges or dismisses a pending analysis, once
  (audited as `ai.risk_review`);
- event trigger: `run_event_risk_analysis` runs the SAME pipeline as the acting user.
"""

import hashlib
import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.ai.graph import AnalysisDenied, build_graph, evidence_window, open_read_only_session
from app.ai.guardrails import GUARDRAIL_VERSION
from app.ai.prompts import PROMPT_VERSION
from app.ai.providers import AIUnavailableError, ModelFactory
from app.ai.risk_signals import ANALYSIS_HORIZON, RULESETS, UNVALIDATED_NOTICE, max_priority
from app.ai.schemas import (
    AIAnalysisRequest,
    AIAnalysisResult,
    AICapabilities,
    AIModelInfo,
    AIToolInfo,
    AnalysisStatus,
    AnalysisType,
    RiskAnalysisListParams,
    RiskContext,
    RiskEngineInfo,
    RiskReviewCreate,
    RiskReviewStatus,
    RiskSignalRead,
    RiskTrigger,
)
from app.ai.tools import TOOL_SPECS
from app.core.audit import AuditRecorder
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import P, Scope
from app.core.principal import Principal
from app.models.ai_review import AIRiskAnalysis
from app.models.audit import AuditOutcome
from app.repositories.ai_risk_repository import AIRiskAnalysisRepository

logger = logging.getLogger(__name__)

OUTCOME = {AnalysisStatus.COMPLETED: AuditOutcome.SUCCESS, AnalysisStatus.ABSTAINED: AuditOutcome.FAILURE,
           AnalysisStatus.REFUSED: AuditOutcome.DENIED}
OBSERVATION_CREATED = "observation.created"


class AIServiceUnavailable(RuntimeError):
    pass


def _reference_now():
    """Default reference time: now, rounded UP to a whole second (models echo it exactly, and records
    written earlier in the same second must still fall inside the evidence window)."""
    now = utc_now()
    return now.replace(microsecond=0) + timedelta(seconds=1) if now.microsecond else now


class AIService:
    def __init__(self, session: Session, settings: Settings, model_factory: ModelFactory) -> None:
        self._session = session
        self._settings = settings
        self._model_factory = model_factory
        self._audit = AuditRecorder(session.get_bind())
        self._risks = AIRiskAnalysisRepository(session)

    def capabilities(self, principal: Principal, enabled: bool) -> AICapabilities:
        return AICapabilities(
            enabled=enabled, provider=self._settings.llm_provider, model=self._settings.llm_model,
            analysis_types=list(AnalysisType),
            tools=[AIToolInfo(name=s.name, description=s.description, required_permission=s.permission.value,
                              read_only=True, available_to_you=principal.has(s.permission)) for s in TOOL_SPECS],
        )

    def analyze(self, principal: Principal, request: AIAnalysisRequest, request_id: str, *,
                trigger: RiskTrigger = RiskTrigger.MANUAL, trigger_event: str | None = None,
                trigger_source_id: uuid.UUID | None = None) -> AIAnalysisResult:
        started = time.perf_counter()
        is_risk = request.analysis_type == AnalysisType.FOUR_DAY_RISK
        reference_at = (request.reference_at or _reference_now()) if is_risk else None
        trigger_details = {"trigger": trigger.value, "trigger_event": trigger_event} if is_risk else {}
        try:
            model = self._model_factory()
        except AIUnavailableError as exc:
            self._record(principal, request, AuditOutcome.FAILURE,
                         {"status": "UNAVAILABLE", "reason": str(exc), **trigger_details}, started)
            raise AIServiceUnavailable("The AI assistant is not configured.") from None

        read_only = open_read_only_session(self._session)
        try:
            graph = build_graph(session=self._session, read_only_session=read_only, model=model,
                                items_per_tool=self._settings.ai_max_items_per_tool,
                                ruleset_id=self._settings.ai_risk_ruleset,
                                lookback_hours=self._settings.ai_risk_evidence_lookback_hours)
            inputs = {"principal": principal, "patient_id": request.patient_id,
                      "analysis_type": request.analysis_type, "question": request.question,
                      "requested_tools": request.tools}
            if is_risk:
                inputs["reference_at"] = reference_at
            state = graph.invoke(inputs)
        except AnalysisDenied as denied:
            self._record(principal, request, AuditOutcome.DENIED,
                         {"status": "DENIED", "reason_code": denied.reason_code, **trigger_details}, started)
            if denied.http_status == 404:
                raise NotFoundError(denied.message) from None
            raise PermissionDeniedError(denied.message) from None
        finally:
            read_only.rollback()
            read_only.close()

        output = state.get("output")
        status = state["status"]
        risk = None
        if is_risk:
            risk = self._risk_context(state, reference_at, trigger)
            if status != AnalysisStatus.REFUSED:
                stored = self._store_risk(principal, request_id, state, reference_at, trigger, trigger_event,
                                          trigger_source_id)
                risk.risk_analysis_id, risk.review_status = stored.id, RiskReviewStatus(stored.review_status)
        result = AIAnalysisResult(
            request_id=request_id,
            status=status,
            reason_code=state.get("reason_code"),
            message=state["message"],
            patient_id=request.patient_id,
            patient_number=state.get("patient_number"),
            analysis_type=request.analysis_type,
            output=output if status == AnalysisStatus.COMPLETED or (
                output is not None and output.status == "ABSTAIN") else None,
            risk=risk,
            tools_used=state.get("tools_used", []),
            tools_withheld=state.get("tools_withheld", []),
            evidence_count=len(state.get("evidence", [])),
            model=AIModelInfo(provider=self._settings.llm_provider, model=self._settings.llm_model),
            generated_at=utc_now(),
        )
        details = {
            "status": result.status.value,
            "reason_code": result.reason_code,
            "tools_used": result.tools_used,
            "tools_withheld": result.tools_withheld,
            "evidence_count": result.evidence_count,
            "cited_sources": [c.source_id for c in output.evidence] if output else [],
            "guardrail_flags": state.get("guardrail_flags", []),
            "model_latency_ms": state.get("model_latency_ms"),
        }
        if risk is not None:  # identifiers and codes only - never signal text
            details.update({
                **trigger_details, "trigger_source_id": str(trigger_source_id) if trigger_source_id else None,
                "risk_analysis_id": str(risk.risk_analysis_id) if risk.risk_analysis_id else None,
                "reference_at": risk.reference_at.isoformat(), "horizon_end": risk.horizon_end.isoformat(),
                "horizon_days": risk.analysis_horizon_days, "ruleset": risk.engine.ruleset_id,
                "ruleset_validated": risk.engine.validated,
                "signals": [f"{s.signal_id}:{s.category.value}:{s.priority.value}" for s in risk.signals],
                "max_priority": risk.max_priority.value if risk.max_priority else None,
            })
        self._record(principal, request, OUTCOME[result.status], details, started)
        return result

    # --- Stage 8: risk context, storage, review ----------------------------------------------

    def _risk_context(self, state: dict, reference_at, trigger: RiskTrigger) -> RiskContext:
        report = state.get("signal_report")
        rules = report.ruleset if report else RULESETS[self._settings.ai_risk_ruleset]
        since, until = evidence_window(reference_at, self._settings.ai_risk_evidence_lookback_hours)
        signals = report.signals if report else []
        return RiskContext(
            reference_at=reference_at, horizon_start=reference_at, horizon_end=reference_at + ANALYSIS_HORIZON,
            evidence_window_start=since, evidence_window_end=until,
            engine=RiskEngineInfo(ruleset_id=rules.ruleset_id, version=rules.version, validated=rules.validated,
                                  notice=UNVALIDATED_NOTICE),
            signals=[RiskSignalRead(**s.as_dict()) for s in signals],
            data_gaps=report.data_gaps if report else [],
            max_priority=max_priority(signals), trigger=trigger,
        )

    def _store_risk(self, principal: Principal, request_id: str, state: dict, reference_at, trigger: RiskTrigger,
                    trigger_event: str | None, trigger_source_id: uuid.UUID | None) -> AIRiskAnalysis:
        report = state.get("signal_report")
        rules = report.ruleset if report else RULESETS[self._settings.ai_risk_ruleset]
        signals = report.signals if report else []
        output = state.get("output")
        top = max_priority(signals)
        stored = self._risks.add(AIRiskAnalysis(
            patient_id=state["patient_id"], status=state["status"].value, reason_code=state.get("reason_code"),
            trigger=trigger.value, trigger_event=trigger_event, trigger_source_id=trigger_source_id,
            request_id=request_id, requested_by_user_id=principal.user_id, requested_by_staff_id=principal.staff_id,
            reference_at=reference_at, horizon_start=reference_at, horizon_end=reference_at + ANALYSIS_HORIZON,
            ruleset_id=rules.ruleset_id, ruleset_version=rules.version, ruleset_validated=rules.validated,
            signals=[s.as_dict() for s in signals], data_gaps=report.data_gaps if report else [],
            max_priority=top.value if top else None,
            output=output.model_dump(mode="json") if output is not None else None,
            provider=self._settings.llm_provider, model=self._settings.llm_model,
            requires_human_review=True, review_status=RiskReviewStatus.PENDING_REVIEW.value,
        ))
        self._session.commit()
        return stored

    def _require_patient_scope(self, principal: Principal) -> None:
        if principal.scope(P.PATIENT_VIEW) != Scope.ALL:
            raise PermissionDeniedError("You are not permitted to view patients' AI risk analyses.")

    def list_risk_analyses(self, principal: Principal, params: RiskAnalysisListParams):
        self._require_patient_scope(principal)
        return self._risks.list(params)

    def get_risk_analysis(self, principal: Principal, analysis_id: uuid.UUID) -> AIRiskAnalysis:
        self._require_patient_scope(principal)
        analysis = self._risks.get(analysis_id)
        if analysis is None:
            raise NotFoundError(f"AI risk analysis {analysis_id} not found.")
        return analysis

    def review_risk_analysis(self, principal: Principal, analysis_id: uuid.UUID,
                             data: RiskReviewCreate) -> AIRiskAnalysis:
        """Record the human review. Changes only the AI record's review fields - never clinical data."""
        details = {"risk_analysis_id": str(analysis_id), "decision": data.decision.value,
                   "has_comment": data.comment is not None}
        if principal.user_id is None or principal.staff_id is None:
            self._record_review(principal, None, AuditOutcome.DENIED, {**details, "reason_code": "human_user_required"})
            raise PermissionDeniedError("AI output can only be reviewed by an authenticated staff user.")
        self._require_patient_scope(principal)
        analysis = self._risks.get(analysis_id, for_update=True)
        if analysis is None:
            raise NotFoundError(f"AI risk analysis {analysis_id} not found.")
        if analysis.review_status != RiskReviewStatus.PENDING_REVIEW.value:
            self._session.rollback()
            self._record_review(principal, analysis.patient_id, AuditOutcome.FAILURE,
                                {**details, "reason_code": "already_reviewed"})
            raise ConflictError(f"AI risk analysis {analysis_id} has already been reviewed "
                                f"({analysis.review_status}).")
        analysis.review_status = data.decision.value
        analysis.reviewed_by_user_id = principal.user_id  # bound to the caller, never taken from the body
        analysis.reviewed_by_staff_id = principal.staff_id
        analysis.reviewed_at = utc_now()
        analysis.review_comment = data.comment
        self._session.commit()
        self._record_review(principal, analysis.patient_id, AuditOutcome.SUCCESS, details)
        return analysis

    def _record_review(self, principal: Principal, patient_id, outcome: AuditOutcome, details: dict) -> None:
        self._audit.record("ai.risk_review", outcome, principal=principal, resource_type="ai_risk_analyses",
                           resource_id=details["risk_analysis_id"], patient_id=patient_id, details=details)

    def _record(self, principal: Principal, request: AIAnalysisRequest, outcome: AuditOutcome, details: dict,
                started: float) -> None:
        question = request.question or ""
        self._audit.record(
            "ai.analysis", outcome, principal=principal,
            resource_type="patients", resource_id=request.patient_id, patient_id=request.patient_id,
            details={**details, "analysis_type": request.analysis_type.value,
                     "provider": self._settings.llm_provider, "model": self._settings.llm_model,
                     "guardrail_version": GUARDRAIL_VERSION, "prompt_version": PROMPT_VERSION,
                     "question_length": len(question),
                     "question_sha256": hashlib.sha256(question.encode()).hexdigest() if question else None,
                     "requested_tools": request.tools, "latency_ms": round((time.perf_counter() - started) * 1000)},
        )


def run_event_risk_analysis(session_factory: sessionmaker, settings: Settings, model_factory: ModelFactory,
                            principal: Principal, patient_id: uuid.UUID, source_id: uuid.UUID, request_id: str,
                            event: str = OBSERVATION_CREATED) -> AIAnalysisResult | None:
    """Event-triggered four-day risk analysis (runs after the triggering request has committed).

    Same graph, guardrails and authorization as a manual request, executed AS THE ACTING USER
    (never a system/staff-less identity). Skipped during the per-patient cooldown. It never
    raises: the triggering clinical write has already succeeded and must not be affected.
    """
    with session_factory() as session:
        try:
            cooldown = timedelta(minutes=settings.ai_risk_trigger_cooldown_minutes)
            if AIRiskAnalysisRepository(session).event_triggered_since(patient_id, utc_now() - cooldown):
                return None
            session.rollback()  # end the read transaction before the analysis
            return AIService(session, settings, model_factory).analyze(
                principal, AIAnalysisRequest(patient_id=patient_id, analysis_type=AnalysisType.FOUR_DAY_RISK),
                request_id, trigger=RiskTrigger.EVENT, trigger_event=event, trigger_source_id=source_id)
        except Exception as exc:  # already audited where applicable; never propagate
            logger.warning("event-triggered risk analysis skipped (%s)", type(exc).__name__)
            return None


__all__ = ["AIService", "AIServiceUnavailable", "OBSERVATION_CREATED", "run_event_risk_analysis"]
