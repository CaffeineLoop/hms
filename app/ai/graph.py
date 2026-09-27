"""The LangGraph workflow of the AI assistant (Stages 7-8).

    START -> authorize -> check_request -> plan_tools -> gather_evidence -> compute_signals
          -> check_evidence -> generate -> validate_output -> END
    (any node may route to END early with status REFUSED / ABSTAINED)

- authorize        human staff-linked user, `ai.analysis`, patient visible at ALL scope, patient exists
- check_request    deterministic input guardrails (injection, extraction, forbidden actions, other
                   patients, out-of-domain) and the requested-tool allowlist
- plan_tools       tools for the analysis type, filtered by the caller's permissions (role-aware)
- gather_evidence  runs the chosen read-only tools (bound to this patient, READ ONLY transaction;
                   FOUR_DAY_RISK: limited to the evidence window ending at the reference time)
- compute_signals  FOUR_DAY_RISK only: deterministic potential-risk signals (app/ai/risk_signals.py)
- check_evidence   abstains when there is no clinical evidence (missing data); flags injected text;
                   FOUR_DAY_RISK also abstains without any observation in the evidence window
- generate         one LLM call: system rules + request + evidence (+ signals) -> JSON
- validate_output  schema, citations, patient, overreach, leakage (FOUR_DAY_RISK: horizon, complete
                   and unaltered signals, hedged wording) -> COMPLETED or ABSTAINED

The model never predicts risk on its own: for FOUR_DAY_RISK it only explains signals computed in
code, and the horizon (reference time + 4 days) is fixed before the model is called.

The graph has no node that writes anything; its only side effect is the audit event written
by the calling service after the run.
"""

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai import guardrails
from app.ai.prompts import build_prompt, build_risk_prompt
from app.ai.risk_signals import ANALYSIS_HORIZON, ANALYSIS_HORIZON_DAYS, UNVALIDATED_NOTICE, SignalReport, compute_signals
from app.ai.schemas import AnalysisStatus, AnalysisType, ModelAnalysisOutput, ModelRiskOutput
from app.ai.tools import ALLOWED_TOOL_NAMES, TOOL_SPECS, TOOLS_BY_NAME, bind_tools
from app.core.permissions import P, Scope
from app.core.principal import Principal
from app.models.patient import Patient

TOOLS_FOR_ANALYSIS: dict[AnalysisType, tuple[str, ...]] = {
    AnalysisType.CLINICAL_SUMMARY: tuple(s.name for s in TOOL_SPECS),
    AnalysisType.QUESTION: tuple(s.name for s in TOOL_SPECS),
    AnalysisType.VITALS_REVIEW: ("get_patient_profile", "get_observations", "get_encounters"),
    AnalysisType.MEDICATION_REVIEW: ("get_patient_profile", "get_medications", "get_allergies", "get_conditions"),
    AnalysisType.LAB_REVIEW: ("get_patient_profile", "get_lab_results", "get_reports", "get_conditions"),
    AnalysisType.FOUR_DAY_RISK: tuple(s.name for s in TOOL_SPECS),
}


class AnalysisState(TypedDict, total=False):
    # inputs
    principal: Principal
    patient_id: uuid.UUID
    analysis_type: AnalysisType
    question: str | None
    requested_tools: list[str] | None
    reference_at: datetime  # FOUR_DAY_RISK: fixed by the service before the graph runs
    # progress
    patient_number: str
    planned_tools: list[str]
    tools_used: list[str]
    tools_withheld: list[str]
    evidence: list[dict[str, Any]]
    signal_report: SignalReport
    guardrail_flags: list[str]
    raw_output: str
    output: ModelAnalysisOutput | ModelRiskOutput
    model_latency_ms: int
    # result
    status: AnalysisStatus
    reason_code: str | None
    message: str
    http_status: int


class AnalysisDenied(Exception):
    """Authorization / scope failures surface as HTTP errors, not as assistant answers."""

    def __init__(self, http_status: int, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.http_status, self.reason_code, self.message = http_status, reason_code, message


def prompt_json(value) -> str:
    """JSON for the prompt with '<' and '>' escaped (Stage 9): record text can never forge the
    <request>/<evidence>/<risk_context> delimiters. The escapes are valid JSON, so values decode unchanged."""
    return json.dumps(value, default=str).replace("<", "\\u003c").replace(">", "\\u003e")


def prompt_text(value: str) -> str:
    """Untrusted free text (the clinician's question) with angle brackets neutralised (Stage 9)."""
    return value.replace("<", "\u2039").replace(">", "\u203a")


def _stop(status: AnalysisStatus, reason: str, message: str) -> dict:
    return {"status": status, "reason_code": reason, "message": message}


def evidence_window(reference_at: datetime, lookback_hours: int) -> tuple[datetime, datetime]:
    return reference_at - timedelta(hours=lookback_hours), reference_at


def build_graph(*, session: Session, read_only_session: Session, model: BaseChatModel, items_per_tool: int,
                ruleset_id: str = "demo-v1", lookback_hours: int = 96):
    parser = PydanticOutputParser(pydantic_object=ModelAnalysisOutput)
    chain = build_prompt() | model | StrOutputParser()
    risk_parser = PydanticOutputParser(pydantic_object=ModelRiskOutput)
    risk_chain = build_risk_prompt() | model | StrOutputParser()

    def is_risk(state: AnalysisState) -> bool:
        return state["analysis_type"] == AnalysisType.FOUR_DAY_RISK

    def authorize(state: AnalysisState) -> dict:
        principal = state["principal"]
        if principal.user_id is None or principal.staff_id is None:
            # Staff-less principals (system/import identities) may never drive the assistant.
            raise AnalysisDenied(403, "human_user_required", "The AI assistant requires an authenticated staff user.")
        if not principal.has(P.AI_ANALYSIS):
            raise AnalysisDenied(403, "missing_permission", "Missing permission: ai.analysis.")
        if principal.scope(P.PATIENT_VIEW) != Scope.ALL:
            raise AnalysisDenied(403, "patient_out_of_scope", "You are not permitted to view this patient.")
        patient = session.get(Patient, state["patient_id"])
        if patient is None:
            raise AnalysisDenied(404, "patient_not_found", f"Patient {state['patient_id']} not found.")
        return {"patient_number": patient.patient_number, "guardrail_flags": [], "tools_used": [],
                "tools_withheld": [], "evidence": []}

    def check_request(state: AnalysisState) -> dict:
        verdict = guardrails.check_requested_tools(state.get("requested_tools"), ALLOWED_TOOL_NAMES)
        if verdict.allowed:
            verdict = guardrails.check_request(state.get("question"), state["analysis_type"],
                                               patient_number=state["patient_number"], patient_id=state["patient_id"])
        return {} if verdict.allowed else _stop(AnalysisStatus.REFUSED, verdict.reason_code, verdict.message)

    def plan_tools(state: AnalysisState) -> dict:
        candidates = list(TOOLS_FOR_ANALYSIS[state["analysis_type"]])
        if state.get("requested_tools"):
            candidates = ["get_patient_profile"] + [t for t in candidates if t in state["requested_tools"]
                                                    and t != "get_patient_profile"]
        principal = state["principal"]
        planned = [t for t in candidates if principal.has(TOOLS_BY_NAME[t].permission)]
        withheld = [t for t in candidates if t not in planned]
        return {"planned_tools": planned, "tools_withheld": withheld}

    def gather_evidence(state: AnalysisState) -> dict:
        since = until = None
        if is_risk(state):
            since, until = evidence_window(state["reference_at"], lookback_hours)
        evidence, used = [], []
        for tool in bind_tools(read_only_session, state["patient_id"], items_per_tool, state["planned_tools"],
                               since=since, until=until):
            evidence.extend(tool.invoke({}))
            used.append(tool.name)
        return {"evidence": evidence, "tools_used": used}

    def compute_signals_node(state: AnalysisState) -> dict:
        if not is_risk(state):
            return {}
        return {"signal_report": compute_signals(state["evidence"], ruleset_id)}

    def check_evidence(state: AnalysisState) -> dict:
        flags = list(state.get("guardrail_flags", [])) + guardrails.evidence_flags(state["evidence"])
        if not any(item["type"] != "patient" for item in state["evidence"]):
            return {**_stop(AnalysisStatus.ABSTAINED, "insufficient_data",
                            "No clinical records are available (or accessible to you) for this patient."),
                    "guardrail_flags": flags}
        if is_risk(state) and state["signal_report"].observation_count == 0:
            return {**_stop(AnalysisStatus.ABSTAINED, "insufficient_recent_data",
                            f"No observations in the last {lookback_hours} hours before the reference time: "
                            "there is not enough information for a four-day potential risk analysis."),
                    "guardrail_flags": flags}
        return {"guardrail_flags": flags}

    def risk_context_json(state: AnalysisState) -> str:
        report, reference_at = state["signal_report"], state["reference_at"]
        return prompt_json({
            "reference_at": reference_at.isoformat(), "horizon_start": reference_at.isoformat(),
            "horizon_end": (reference_at + ANALYSIS_HORIZON).isoformat(),
            "analysis_horizon_days": ANALYSIS_HORIZON_DAYS,
            "ruleset": {"id": report.ruleset.ruleset_id, "version": report.ruleset.version,
                        "validated": report.ruleset.validated, "notice": UNVALIDATED_NOTICE},
            "signals": [signal.as_dict() for signal in report.signals],
            "data_gaps": report.data_gaps,
        })

    def generate(state: AnalysisState) -> dict:
        request = {"patient_number": state["patient_number"], "analysis_type": state["analysis_type"].value}
        inputs = {
            "format_instructions": parser.get_format_instructions(),
            "request_json": prompt_json(request),
            "evidence_json": prompt_json(state["evidence"]),
            "withheld": ", ".join(state["tools_withheld"]) or "none",
            "question": prompt_text(state.get("question") or "(none - produce the requested analysis type)"),
        }
        started = time.perf_counter()
        try:
            if is_risk(state):
                raw = risk_chain.invoke({**inputs, "format_instructions": risk_parser.get_format_instructions(),
                                         "risk_json": risk_context_json(state)})
            else:
                raw = chain.invoke(inputs)
        except Exception as exc:  # provider/network/timeout: abstain safely, never crash the request
            return {**_stop(AnalysisStatus.ABSTAINED, "model_unavailable",
                            "The language model could not be reached; no analysis was produced."),
                    "guardrail_flags": state["guardrail_flags"] + [f"model_error:{type(exc).__name__}"]}
        return {"raw_output": raw, "model_latency_ms": round((time.perf_counter() - started) * 1000)}

    def validate_output(state: AnalysisState) -> dict:
        output, error = guardrails.parse_model_output(state["raw_output"],
                                                      ModelRiskOutput if is_risk(state) else ModelAnalysisOutput)
        if output is None:
            return {**_stop(AnalysisStatus.ABSTAINED, "invalid_model_output",
                            "The model's answer did not match the required structure and was discarded."),
                    "guardrail_flags": state["guardrail_flags"] + [f"parse_error:{error}"]}
        evidence_ids = {e["source_id"] for e in state["evidence"]}
        if is_risk(state):
            verdict = guardrails.check_risk_output(output, patient_number=state["patient_number"],
                                                   reference_at=state["reference_at"],
                                                   signals=state["signal_report"].signals, evidence_ids=evidence_ids,
                                                   evidence=state["evidence"])
        else:
            verdict = guardrails.check_output(output, analysis_type=state["analysis_type"],
                                              patient_number=state["patient_number"], evidence_ids=evidence_ids,
                                              evidence=state["evidence"])
        if not verdict.allowed:
            return {**_stop(AnalysisStatus.ABSTAINED, verdict.reason_code, verdict.message),
                    "guardrail_flags": state["guardrail_flags"] + [verdict.reason_code]}
        if output.status == "ABSTAIN":
            return {**_stop(AnalysisStatus.ABSTAINED, "model_abstained", output.abstain_reason), "output": output}
        message = ("Potential risk signals for the next 4 days, generated from the cited records. "
                   "Suggestions only - clinician review required." if is_risk(state)
                   else "Analysis generated from the cited records. Clinician review required.")
        return {"output": output, "status": AnalysisStatus.COMPLETED, "reason_code": None, "message": message}

    def route_after(state: AnalysisState) -> Literal["continue", "stop"]:
        return "stop" if state.get("status") else "continue"

    graph = StateGraph(AnalysisState)
    for name, node in (("authorize", authorize), ("check_request", check_request), ("plan_tools", plan_tools),
                       ("gather_evidence", gather_evidence), ("compute_signals", compute_signals_node),
                       ("check_evidence", check_evidence),
                       ("generate", generate), ("validate_output", validate_output)):
        graph.add_node(name, node)
    graph.add_edge(START, "authorize")
    graph.add_edge("authorize", "check_request")
    graph.add_conditional_edges("check_request", route_after, {"continue": "plan_tools", "stop": END})
    graph.add_edge("plan_tools", "gather_evidence")
    graph.add_edge("gather_evidence", "compute_signals")
    graph.add_edge("compute_signals", "check_evidence")
    graph.add_conditional_edges("check_evidence", route_after, {"continue": "generate", "stop": END})
    graph.add_conditional_edges("generate", route_after, {"continue": "validate_output", "stop": END})
    graph.add_edge("validate_output", END)
    return graph.compile()


def open_read_only_session(session: Session) -> Session:
    """A separate session whose transaction is READ ONLY: PostgreSQL rejects any write through it."""
    read_only = Session(bind=session.get_bind())
    read_only.execute(text("SET TRANSACTION READ ONLY"))
    return read_only


__all__ = ["AnalysisDenied", "AnalysisState", "TOOLS_FOR_ANALYSIS", "build_graph", "evidence_window",
           "open_read_only_session"]
