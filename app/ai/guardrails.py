"""Deterministic guardrails for the AI assistant (Stage 7).

These run in code, before and after the model - they do not rely on the model behaving.

Input (before any data is read or any model is called):
    prompt injection, system-prompt extraction, forbidden clinical actions / treatment
    recommendations, references to other patients, out-of-domain requests, unknown tools.
Output (before anything is returned):
    schema validity, patient reference, citations only to evidence actually provided,
    clinical overreach (prescribing / ordering / definitive diagnosis language), other-patient
    identifiers, system-prompt leakage.
Evidence (records are untrusted text): instruction-like content is flagged, never obeyed.
"""

import json
import re
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.schemas import AnalysisType, ModelAnalysisOutput

# A marker that only appears in the system prompt; seeing it in output means the prompt leaked.
SYSTEM_PROMPT_CANARY = "HMS-AI-GUARD-7c1d"


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason_code: str | None = None
    message: str = ""


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


PROMPT_INJECTION = [
    r"\bignore\b.{0,40}\b(instruction|rule|prompt|guardrail|polic)",
    r"\bdisregard\b.{0,40}\b(instruction|rule|prompt|above|previous)",
    r"\bforget\b.{0,30}\b(instruction|rule|everything|previous)",
    r"\byou are now\b", r"\bact as\b", r"\bpretend (to be|you)\b", r"\broleplay\b",
    r"\b(jailbreak|DAN mode|developer mode|god mode)\b",
    r"\bnew (instructions|rules|persona)\b", r"\boverride\b.{0,30}\b(safety|rules|restrictions|instructions)",
    r"</?(system|evidence|request|instructions)>", r"\[\s*system\s*\]", r"^\s*system\s*:",
    r"\bwithout (any )?(restrictions|limits|guardrails|safety)\b",
]
SYSTEM_PROMPT_EXTRACTION = [
    r"\b(system|initial|hidden|original)\s+(prompt|instructions|message)\b",
    r"\b(reveal|show|print|repeat|output|display|tell me|what are|leak)\b.{0,40}\b(your|the)\b.{0,20}"
    r"\b(prompt|instructions|rules|guidelines|configuration)\b",
    r"\bwhat were you told\b", r"\bverbatim\b.{0,30}\b(above|instructions|prompt)\b",
]
FORBIDDEN_ACTIONS = [
    r"\b(prescribe|dispense|administer)\b",
    r"(?<!in )\b(order|book|schedule)\b.{0,40}\b(test|lab\w*|scan|x-?ray|mri|ct|imaging|appointment|smear|"
    r"culture|panel|count|cbc|fbc|screen\w*|biopsy|investigation\w*|ultrasound|ecg|echo\w*|swab)",
    r"(?<!in )\b(re-?)?order (a|an|the|some|another|repeat|more)\b",
    r"\b(admit|discharge|transfer)\b.{0,20}\b(the )?(patient|him|her|them)\b",
    r"\b(update|modify|change|edit|delete|remove|cancel|create|add|insert|save)\b.{0,40}"
    r"\b(record|chart|note|diagnos\w*|condition|allerg\w*|prescription|medication|order|result|role|permission|user|patient)",
    r"\b(start|stop|increase|decrease|titrate|switch)\b.{0,30}\b(medication|drug|dose|dosage|treatment|therapy)\b",
    r"\b(what|which)\b.{0,20}\b(dose|dosage)\b", r"\bhow (much|many mg)\b.{0,30}\b(give|take|administer)\b",
    r"\b(treatment plan|treat (him|her|them|the patient)|should (i|we) (give|treat|start))\b",
    r"\b(make|give|confirm)\b.{0,20}\b(a |the )?(definitive |final )?diagnos",
    r"\bgrant\b.{0,20}\b(role|permission|access)\b",
]
CROSS_PATIENT = [r"\b(other|another|all|every|different|any other)\s+patients?\b", r"\blist (of )?patients\b",
                 r"\bcompare (him|her|them|this patient) (with|to)\b"]
PATIENT_NUMBER = re.compile(r"\bPAT-\d{6,}\b", re.I)
UUID_TEXT = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
CLINICAL_VOCABULARY = re.compile(
    r"\b(patient|clinic\w*|vital\w*|heart|pulse|blood|pressure|bp|temp\w*|fever|spo2|oxygen|sat\w*|resp\w*|"
    r"weight|glucose|sugar|lab\w*|test|result\w*|report\w*|note\w*|history|condition\w*|diagnos\w*|symptom\w*|"
    r"allerg\w*|medic\w*|drug\w*|prescri\w*|trend\w*|encounter\w*|visit\w*|admission|summar\w*|change\w*|"
    r"abnormal\w*|risk\w*|pain|infection|anaemia|anemia|hb|haemoglobin|hemoglobin|creatinine|renal|cardiac|"
    r"chronic|acute|recent\w*|status|course|finding\w*|problem\w*|concern\w*|improv\w*|worse\w*|stable)\b",
    re.I,
)
OVERREACH = [
    r"\bI (have )?(prescribed|ordered|admitted|discharged|updated|changed|recorded|diagnosed)\b",
    r"\b(prescribe|administer|give|start|initiate)\b.{0,30}\b\d+(\.\d+)?\s?(mg|mcg|g|ml|units?|iu)\b",
    r"\b\d+(\.\d+)?\s?(mg|mcg|ml|units?|iu)\b.{0,30}\b(daily|bd|bid|tds|tid|qid|od|every|hourly|stat)\b",
    r"\bthe (definitive |final |confirmed )?diagnosis is\b", r"\bdiagnosed with\b.{0,40}\b(confirmed|definitely)\b",
    r"\b(you|clinician) (must|should) (prescribe|order|admit|discharge|stop|start)\b",
]
EVIDENCE_INSTRUCTIONS = PROMPT_INJECTION + SYSTEM_PROMPT_EXTRACTION


def check_request(question: str | None, analysis_type: AnalysisType, *, patient_number: str,
                  patient_id: uuid.UUID) -> Verdict:
    if not question:
        return Verdict(True)
    if _any(SYSTEM_PROMPT_EXTRACTION, question):
        return Verdict(False, "system_prompt_extraction", "Requests for the assistant's instructions are not answered.")
    if _any(PROMPT_INJECTION, question):
        return Verdict(False, "prompt_injection", "The request tries to change the assistant's rules and was refused.")
    if _any(FORBIDDEN_ACTIONS, question):
        return Verdict(False, "forbidden_clinical_action",
                       "The assistant is read-only analysis: it cannot diagnose, prescribe, order, change records "
                       "or recommend treatment.")
    other_numbers = {n.upper() for n in PATIENT_NUMBER.findall(question)} - {patient_number.upper()}
    other_ids = {u.lower() for u in UUID_TEXT.findall(question)} - {str(patient_id)}
    if other_numbers or other_ids or _any(CROSS_PATIENT, question):
        return Verdict(False, "cross_patient_reference", "Only the selected patient can be analysed.")
    if analysis_type == AnalysisType.QUESTION and not CLINICAL_VOCABULARY.search(question):
        return Verdict(False, "out_of_domain", "The assistant only answers clinical questions about this patient.")
    return Verdict(True)


def check_requested_tools(requested: list[str] | None, allowed: frozenset[str]) -> Verdict:
    unknown = sorted(set(requested or []) - allowed)
    if unknown:
        return Verdict(False, "forbidden_tool", f"Unknown or forbidden tool(s): {', '.join(unknown)}.")
    return Verdict(True)


def evidence_flags(evidence: list[dict]) -> list[str]:
    text = json.dumps([e.get("data") for e in evidence])
    return ["evidence_contains_instruction_like_text"] if _any(EVIDENCE_INSTRUCTIONS, text) else []


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_model_output(raw: str) -> tuple[ModelAnalysisOutput | None, str | None]:
    text = raw.strip()
    fenced = _JSON_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return ModelAnalysisOutput.model_validate(json.loads(text)), None
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        return None, type(exc).__name__


def check_output(output: ModelAnalysisOutput, *, analysis_type: AnalysisType, patient_number: str,
                 evidence_ids: set[str]) -> Verdict:
    if output.patient_reference.upper() != patient_number.upper():
        return Verdict(False, "patient_mismatch", "The model referred to a different patient.")
    if output.analysis_type != analysis_type:
        return Verdict(False, "analysis_type_mismatch", "The model answered a different analysis type.")
    cited = {c.source_id for c in output.evidence}
    if not cited <= evidence_ids:
        return Verdict(False, "unsupported_citation", "The model cited sources that were not provided.")
    text = " ".join([output.analysis, *output.review_suggestions, *output.limitations, output.abstain_reason or ""])
    if SYSTEM_PROMPT_CANARY.lower() in text.lower():
        return Verdict(False, "system_prompt_leak", "The response disclosed internal instructions.")
    if {n.upper() for n in PATIENT_NUMBER.findall(text)} - {patient_number.upper()}:
        return Verdict(False, "cross_patient_output", "The response referred to another patient.")
    if _any(OVERREACH, text):
        return Verdict(False, "clinical_overreach",
                       "The response contained prescribing, ordering or definitive-diagnosis language.")
    return Verdict(True)
