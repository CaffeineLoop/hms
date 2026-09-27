"""Stage 8 unit tests: four-day potential risk analysis (no database, no network).

Covers the fixed horizon, the deterministic signal layer, the risk output contract (structural)
and its semantic guardrails, and the fake/Gemini-shaped output handling.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from pydantic import ValidationError

from app.ai import guardrails
from app.ai.prompts import RISK_RULES, build_risk_prompt
from app.ai.providers import DeterministicClinicalModel
from app.ai.risk_signals import (
    ANALYSIS_HORIZON,
    ANALYSIS_HORIZON_DAYS,
    DEMO_V1,
    RULESETS,
    UNVALIDATED_NOTICE,
    ReviewPriority,
    SignalCategory,
    compute_signals,
    max_priority,
)
from app.ai.schemas import AIAnalysisRequest, ModelRiskOutput
from app.core.config import load_settings

PID = uuid.uuid4()
PATIENT_NUMBER = "PAT-000123"
REF = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _item(kind: str, minutes_ago: float, data: dict) -> dict:
    at = (REF - timedelta(minutes=minutes_ago)).isoformat()
    return {"source_id": f"{kind}:{uuid.uuid4()}", "type": kind, "occurred_at": at, "data": data}


def obs(code: str, value, unit: str, minutes_ago: float) -> dict:
    return _item("observation", minutes_ago, {"code": code, "display": code.replace("_", " "), "value": value,
                                              "unit": unit, "effective_at": None})


def lab(analyte: str, value, low=None, high=None, interpretation=None, minutes_ago=60) -> dict:
    return _item("lab_result", minutes_ago, {"test": "Panel", "analyte": analyte, "value": value, "unit": "x",
                                             "reference_low": low, "reference_high": high, "reference_text": None,
                                             "interpretation": interpretation, "resulted_at": None})


def allergy(substance: str, status: str = "ACTIVE") -> dict:
    return _item("allergy", 5000, {"substance": substance, "category": "MEDICATION", "reaction": "rash",
                                   "severity": "SEVERE", "status": status})


def prescription(medicine: str, status: str = "ACTIVE") -> dict:
    return _item("prescription", 600, {"status": status, "prescribed_at": None,
                                       "items": [{"medicine": medicine, "dose": "500 mg", "route": "ORAL",
                                                  "frequency": "TID", "duration": "5 DAYS"}]})


PROFILE = {"source_id": f"patient:{PID}", "type": "patient", "occurred_at": None,
           "data": {"patient_number": PATIENT_NUMBER, "age_years": 40, "sex": "FEMALE", "status": "ACTIVE"}}


def signals_for(*items):
    return compute_signals([PROFILE, *items], "demo-v1")


# --- the horizon is fixed -----------------------------------------------------------------------


def test_horizon_is_a_fixed_four_day_constant():
    assert ANALYSIS_HORIZON_DAYS == 4 and ANALYSIS_HORIZON == timedelta(days=4)
    settings = load_settings()
    assert not any("horizon" in name for name in type(settings).model_fields)  # not configurable


def test_request_accepts_only_a_four_day_horizon():
    assert AIAnalysisRequest(patient_id=PID, analysis_type="FOUR_DAY_RISK", analysis_horizon_days=4)
    for days in (1, 3, 5, 7, 30, 0, -4):
        with pytest.raises(ValidationError):
            AIAnalysisRequest(patient_id=PID, analysis_type="FOUR_DAY_RISK", analysis_horizon_days=days)


def test_request_reference_time_rules():
    request = AIAnalysisRequest(patient_id=PID, analysis_type="FOUR_DAY_RISK",
                                reference_at="2026-09-01T10:15:30.987654+03:00")
    assert request.reference_at == datetime(2026, 9, 1, 7, 15, 30, tzinfo=UTC)  # UTC, whole seconds
    with pytest.raises(ValidationError, match="future"):
        AIAnalysisRequest(patient_id=PID, analysis_type="FOUR_DAY_RISK",
                          reference_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    with pytest.raises(ValidationError):  # naive timestamps are ambiguous
        AIAnalysisRequest(patient_id=PID, analysis_type="FOUR_DAY_RISK", reference_at="2026-09-01T10:00:00")
    for other in ("CLINICAL_SUMMARY", "VITALS_REVIEW"):
        with pytest.raises(ValidationError, match="FOUR_DAY_RISK analyses only"):
            AIAnalysisRequest(patient_id=PID, analysis_type=other, reference_at="2026-09-01T10:00:00Z")
        with pytest.raises(ValidationError, match="FOUR_DAY_RISK analyses only"):
            AIAnalysisRequest(patient_id=PID, analysis_type=other, analysis_horizon_days=4)


# --- risk output contract (structural) -----------------------------------------------------------


def _output(**overrides) -> dict:
    base = {"status": "ANALYSIS", "analysis_type": "FOUR_DAY_RISK", "patient_reference": PATIENT_NUMBER,
            "reference_at": REF.isoformat(), "horizon_start": REF.isoformat(),
            "horizon_end": (REF + ANALYSIS_HORIZON).isoformat(), "analysis_horizon_days": 4,
            "summary": "One potential risk signal may warrant clinical review.", "risk_signals": [],
            "observed_trends": [], "evidence": [], "limitations": ["Signal rules are not clinically validated."],
            "precautionary_suggestions": ["Clinician may wish to review the cited readings."],
            "requires_human_review": True, "abstain_reason": None}
    return {**base, **overrides}


@pytest.mark.parametrize("overrides", [
    {"horizon_end": (REF + timedelta(days=5)).isoformat()},
    {"horizon_end": (REF + timedelta(days=3)).isoformat()},
    {"horizon_end": (REF + timedelta(days=30)).isoformat()},
    {"analysis_horizon_days": 5},
    {"analysis_horizon_days": 7},
    {"horizon_start": (REF + timedelta(hours=1)).isoformat(),
     "horizon_end": (REF + timedelta(days=4, hours=1)).isoformat()},
    {"requires_human_review": False},
    {"analysis_type": "CLINICAL_SUMMARY"},
    {"diagnosis": "sepsis"},  # extra fields are forbidden
    {"reference_at": "2026-09-27T12:00:00"},  # naive
    {"status": "ABSTAIN", "abstain_reason": None},
])
def test_risk_output_structure_is_enforced(overrides):
    with pytest.raises(ValidationError):
        ModelRiskOutput.model_validate(_output(evidence=[{"source_id": "observation:x", "relevance": "r"}],
                                               **overrides))


def test_risk_output_requires_citations_and_unique_signals():
    with pytest.raises(ValidationError, match="cite at least one"):
        ModelRiskOutput.model_validate(_output())
    signal = {"signal_id": "SIG-01", "category": "VITAL_SIGN", "priority": "HIGH", "explanation": "May warrant review.",
              "evidence": ["observation:x"]}
    with pytest.raises(ValidationError, match="unique"):
        ModelRiskOutput.model_validate(_output(risk_signals=[signal, signal],
                                               evidence=[{"source_id": "observation:x", "relevance": "r"}]))


# --- deterministic signal layer ------------------------------------------------------------------


def test_ruleset_is_explicitly_unvalidated_and_replaceable():
    assert RULESETS == {"demo-v1": DEMO_V1}
    assert DEMO_V1.validated is False and "NOT clinically validated" in DEMO_V1.description
    assert "NOT clinically validated" in UNVALIDATED_NOTICE
    assert load_settings().ai_risk_ruleset == "demo-v1"
    with pytest.raises(Exception, match="AI_RISK_RULESET"):
        load_settings(ai_risk_ruleset="validated-v9")


def test_event_trigger_configuration():
    assert load_settings(ai_risk_event_triggers="").risk_triggers == frozenset()
    assert load_settings(ai_risk_event_triggers=" observation.created ").risk_triggers == {"observation.created"}
    with pytest.raises(Exception, match="AI_RISK_EVENT_TRIGGERS"):
        load_settings(ai_risk_event_triggers="observation.created,patient.deleted")


def test_out_of_band_vital_signals_cite_their_record():
    temp = obs("body_temperature", 38.6, "Cel", 30)
    spo2 = obs("oxygen_saturation", 88, "%", 30)
    normal_hr = obs("heart_rate", 80, "/min", 30)
    report = signals_for(temp, spo2, normal_hr)
    by_rule = {s.rule_id: s for s in report.signals}
    assert set(by_rule) == {"demo-v1.vital_high.body_temperature", "demo-v1.vital_low.oxygen_saturation"}
    assert by_rule["demo-v1.vital_high.body_temperature"].priority == ReviewPriority.MODERATE
    assert by_rule["demo-v1.vital_low.oxygen_saturation"].priority == ReviewPriority.HIGH  # <= 90
    assert by_rule["demo-v1.vital_high.body_temperature"].evidence == (temp["source_id"],)
    assert by_rule["demo-v1.vital_low.oxygen_saturation"].evidence == (spo2["source_id"],)
    assert [s.signal_id for s in report.signals] == ["SIG-01", "SIG-02"]  # HIGH first
    assert report.signals[0].category == SignalCategory.VITAL_SIGN


def test_only_the_latest_reading_is_banded_and_units_are_converted():
    old_fever = obs("body_temperature", 39.0, "Cel", 300)
    now_normal = obs("body_temperature", 98.6, "[degF]", 10)  # 37.0 Cel
    assert [s.rule_id for s in signals_for(old_fever, now_normal).signals] == []
    glucose = obs("blood_glucose", 50, "mg/dL", 10)  # 2.78 mmol/L -> HIGH priority low band
    (signal,) = signals_for(glucose).signals
    assert signal.rule_id == "demo-v1.vital_low.blood_glucose" and signal.priority == ReviewPriority.HIGH


def test_monotonic_trend_signal_and_non_monotonic_series():
    readings = [obs("heart_rate", v, "/min", m) for v, m in ((82, 180), (91, 120), (104, 30))]
    report = signals_for(*readings)
    (trend,) = [s for s in report.signals if s.category == SignalCategory.VITAL_TREND]
    assert trend.rule_id == "demo-v1.trend.heart_rate"
    assert set(trend.evidence) == {r["source_id"] for r in readings}
    zigzag = [obs("heart_rate", v, "/min", m) for v, m in ((82, 180), (110, 120), (95, 60), (104, 30))]
    assert not [s for s in signals_for(*zigzag).signals if s.category == SignalCategory.VITAL_TREND]


def test_conflicting_readings_produce_a_data_conflict_signal():
    a, b = obs("body_temperature", 36.4, "Cel", 20), obs("body_temperature", 39.1, "Cel", 10)
    report = signals_for(a, b)
    (conflict,) = [s for s in report.signals if s.category == SignalCategory.DATA_CONFLICT]
    assert set(conflict.evidence) == {a["source_id"], b["source_id"]}
    assert "may be erroneous" in conflict.detail


def test_lab_and_medication_safety_signals():
    critical = lab("Potassium", 6.9, 3.5, 5.1, "CRITICAL_HIGH")
    out_of_range = lab("Haemoglobin", 8.1, 12.0, 16.0, None)
    normal = lab("Sodium", 140, 135, 145, "NORMAL")
    pen_allergy, amoxi = allergy("Penicillin"), prescription("Phenoxymethylpenicillin")
    inactive, other_rx = allergy("Sulfa", status="RESOLVED"), prescription("Sulfamethoxazole")
    report = signals_for(critical, out_of_range, normal, pen_allergy, amoxi, inactive, other_rx)
    labs = [s for s in report.signals if s.category == SignalCategory.LAB_RESULT]
    assert {s.evidence for s in labs} == {(critical["source_id"],), (out_of_range["source_id"],)}
    assert {s.priority for s in labs} == {ReviewPriority.HIGH, ReviewPriority.MODERATE}
    (safety,) = [s for s in report.signals if s.category == SignalCategory.MEDICATION_SAFETY]
    assert safety.evidence == (pen_allergy["source_id"], amoxi["source_id"]) and safety.priority == ReviewPriority.HIGH
    assert max_priority(report.signals) == ReviewPriority.HIGH


def test_missing_data_is_a_gap_not_a_signal_and_signals_are_deterministic():
    items = [obs("heart_rate", 120, "/min", 15)]
    first, second = signals_for(*items), signals_for(*items)
    assert [s.as_dict() for s in first.signals] == [s.as_dict() for s in second.signals]
    assert any("body_temperature" in gap for gap in first.data_gaps)
    assert any("lab results" in gap for gap in first.data_gaps)
    evidence_ids = {i["source_id"] for i in items}
    assert all(set(s.evidence) <= evidence_ids and s.evidence for s in first.signals)
    empty = signals_for()
    assert empty.signals == [] and empty.observation_count == 0 and empty.data_gaps


# --- semantic validation of the model's answer ---------------------------------------------------

TEMP = obs("body_temperature", 38.6, "Cel", 30)
HR = [obs("heart_rate", v, "/min", m) for v, m in ((82, 180), (91, 120), (112, 30))]
EVIDENCE = [PROFILE, TEMP, *HR]
REPORT = compute_signals(EVIDENCE, "demo-v1")
EVIDENCE_IDS = {e["source_id"] for e in EVIDENCE}


def _fake_answer() -> dict:
    """What the deterministic fake model returns for EVIDENCE (a real prompt round trip)."""
    risk_json = json.dumps({"reference_at": REF.isoformat(), "horizon_start": REF.isoformat(),
                            "horizon_end": (REF + ANALYSIS_HORIZON).isoformat(), "analysis_horizon_days": 4,
                            "ruleset": {"id": "demo-v1"}, "signals": [s.as_dict() for s in REPORT.signals],
                            "data_gaps": REPORT.data_gaps})
    messages = build_risk_prompt().format_messages(
        format_instructions="{}", request_json=json.dumps({"patient_number": PATIENT_NUMBER,
                                                           "analysis_type": "FOUR_DAY_RISK"}),
        evidence_json=json.dumps(EVIDENCE), withheld="none", question="(none)", risk_json=risk_json)
    return json.loads(DeterministicClinicalModel().invoke(messages).content)


def _check(answer: dict, reference_at: datetime = REF):
    output = ModelRiskOutput.model_validate(answer)
    return guardrails.check_risk_output(output, patient_number=PATIENT_NUMBER, reference_at=reference_at,
                                        signals=REPORT.signals, evidence_ids=EVIDENCE_IDS)


def test_fake_model_answer_passes_semantic_validation():
    answer = _fake_answer()
    assert len(REPORT.signals) == 3  # temperature band, heart-rate band, heart-rate trend
    assert {s["signal_id"] for s in answer["risk_signals"]} == {s.signal_id for s in REPORT.signals}
    assert answer["analysis_horizon_days"] == 4 and answer["requires_human_review"] is True
    assert _check(answer).allowed


def test_reference_time_mismatch_is_rejected():
    assert _check(_fake_answer(), reference_at=REF - timedelta(hours=1)).reason_code == "horizon_mismatch"


def _with_signal(index: int, **changes) -> dict:
    answer = _fake_answer()
    answer["risk_signals"][index] = {**answer["risk_signals"][index], **changes}
    return answer


def test_signal_layer_is_authoritative():
    answer = _fake_answer()
    answer["risk_signals"].append({"signal_id": "SIG-09", "category": "VITAL_SIGN", "priority": "HIGH",
                                   "explanation": "Possible concern.", "evidence": [TEMP["source_id"]]})
    assert _check(answer).reason_code == "unsupported_risk_signal"
    answer = _fake_answer()
    answer["risk_signals"].pop()
    assert _check(answer).reason_code == "risk_signal_omitted"
    assert _check(_with_signal(0, priority="LOW")).reason_code == "risk_signal_altered"
    assert _check(_with_signal(0, category="LAB_RESULT")).reason_code == "risk_signal_altered"
    other = next(i for i in EVIDENCE_IDS if i not in REPORT.signals[0].evidence and i.startswith("observation"))
    assert _check(_with_signal(0, evidence=[other])).reason_code == "unsupported_citation"


def test_citations_must_reference_provided_records():
    answer = _fake_answer()
    answer["evidence"].append({"source_id": f"observation:{uuid.uuid4()}", "relevance": "invented"})
    assert _check(answer).reason_code == "unsupported_citation"
    answer = _fake_answer()
    answer["observed_trends"] = [{"description": "Possible pattern.", "evidence": [f"lab_result:{uuid.uuid4()}"]}]
    assert _check(answer).reason_code == "unsupported_citation"


@pytest.mark.parametrize("text, reason", [
    ("The patient will deteriorate within 48 hours.", "overconfident_risk_language"),
    ("This is definitely an early infection.", "overconfident_risk_language"),
    ("There is a 72% chance of ICU admission.", "overconfident_risk_language"),
    ("The patient has sepsis.", "overconfident_risk_language"),
    ("This validated score predicts that the patient deteriorates.", "overconfident_risk_language"),
    ("Sepsis is confirmed.", "overconfident_risk_language"),
    ("The diagnosis is sepsis.", "clinical_overreach"),
    ("Start IV antibiotics now.", "clinical_overreach"),
    ("Give 1 g paracetamol every 6 hours.", "clinical_overreach"),
    ("Recommend ordering a blood culture and lactate.", "clinical_overreach"),
    ("Escalate care to the ICU.", "clinical_overreach"),
])
def test_overreach_and_certainty_are_rejected(text, reason):
    assert _check({**_fake_answer(), "summary": text}).reason_code == reason
    assert _check(_with_signal(0, explanation=f"Potential concern: {text}")).reason_code == reason


def test_suggestions_must_be_review_oriented():
    answer = {**_fake_answer(), "precautionary_suggestions": ["Prescribe oral fluids."]}
    assert _check(answer).reason_code == "clinical_overreach"
    answer = {**_fake_answer(), "precautionary_suggestions": ["Keep the patient comfortable."]}
    assert _check(answer).reason_code == "non_review_suggestion"
    ok = {**_fake_answer(), "precautionary_suggestions": ["Clinician may wish to re-measure the temperature.",
                                                          "Consider verifying the heart-rate readings."]}
    assert _check(ok).allowed


def test_signal_explanations_must_be_hedged():
    assert _check(_with_signal(0, explanation="Temperature 38.6.")).reason_code == "unhedged_risk_language"


def test_denying_validation_is_allowed_but_claiming_it_is_not():
    answer = {**_fake_answer(), "limitations": ["These rules have not been clinically validated."]}
    assert _check(answer).allowed
    answer = {**_fake_answer(), "limitations": ["Based on a clinically validated rule set."]}
    assert _check(answer).reason_code == "overconfident_risk_language"


def test_other_patients_and_prompt_leaks_are_rejected():
    assert _check({**_fake_answer(), "summary": "Similar to PAT-999999, may warrant review."}).reason_code \
        == "cross_patient_output"
    assert _check({**_fake_answer(), "summary": f"Rules {guardrails.SYSTEM_PROMPT_CANARY} may apply."}).reason_code \
        == "system_prompt_leak"
    assert _check({**_fake_answer(), "patient_reference": "PAT-999999"}).reason_code == "patient_mismatch"


def test_abstaining_is_always_acceptable():
    answer = {**_fake_answer(), "status": "ABSTAIN", "risk_signals": [], "evidence": [], "summary": "",
              "abstain_reason": "The evidence is conflicting."}
    assert _check(answer).allowed


# --- provider compatibility ----------------------------------------------------------------------


def test_gemini_content_parts_parse_into_the_risk_contract():
    """Gemini 3.x returns a list of content parts (with a thought signature); the chain's
    StrOutputParser must turn it into the same JSON text the fake model produces."""
    text = json.dumps(_fake_answer())
    message = AIMessage(content=[{"type": "text", "text": text[:50], "extras": {"signature": "abc"}},
                                 {"type": "text", "text": text[50:]}])
    parsed, error = guardrails.parse_model_output(StrOutputParser().invoke(message), ModelRiskOutput)
    assert error is None and _check(parsed.model_dump(mode="json")).allowed
    fenced, error = guardrails.parse_model_output(f"```json\n{text}\n```", ModelRiskOutput)
    assert error is None and fenced.analysis_horizon_days == 4


def test_risk_prompt_states_the_rules():
    for phrase in ("EXACTLY", "NOT clinically", "Do not add signals", "potential concern", "Never recommend"):
        assert phrase in RISK_RULES
    instructions = PydanticOutputParser(pydantic_object=ModelRiskOutput).get_format_instructions()
    assert "analysis_horizon_days" in instructions and "risk_signals" in instructions
