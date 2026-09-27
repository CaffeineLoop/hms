"""Deterministic guardrails for the AI assistant (Stages 7-9).

These run in code, before and after the model - they do not rely on the model behaving.

Input (before any data is read or any model is called):
    prompt injection, system-prompt extraction, forbidden clinical actions / treatment
    recommendations, references to other patients, out-of-domain requests, horizons other than
    four days, unknown tools.
Output (before anything is returned):
    schema validity, patient reference, citations only to evidence actually provided,
    clinical overreach (diagnosis / prognosis / prescribing / ordering / disposition / escalation
    language), measurements not present in the evidence, other-patient identifiers,
    system-prompt leakage.
Evidence (records are untrusted text): instruction-like content is flagged, never obeyed.
Four-day risk output (Stage 8, `check_risk_output`): exact reference time and 4-day horizon, the
deterministic signals returned complete and unaltered, every citation/evidence id provided,
hedged "potential concern" wording, review-oriented suggestions only, and no certainty,
prediction, validation, diagnosis or treatment/ordering claims.

Stage 9 (adversarial testing) hardening - each item fixes a failure demonstrated by
tests/unit/test_ai_adversarial_guardrails.py or tests/integration/test_ai_adversarial_api.py:
- all text is normalized before matching (Unicode NFKC, invisible/format characters removed,
  common Cyrillic/Greek look-alike letters mapped to Latin, s p a c e d letters joined) and
  base64-looking payloads are decoded and scanned too;
- more injection/extraction phrasings (a few non-English), domain-escape and overreach patterns;
- Stage 7 outputs now get the same action/prognosis checks as risk outputs;
- `ungrounded_measurement`: numbers with clinical units must appear in the evidence;
- Stage 10: `ungrounded_clinical_claim` - named conditions, medications and clinical events must
  appear in the evidence (app/ai/grounding.py);
- horizon wording other than four days is refused (input) or rejected (risk output).
These are pattern checks: they reduce risk, they are not exhaustive (see the Stage 9 report).
"""

import base64
import binascii
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from app.ai.grounding import ungrounded_claims
from app.ai.risk_signals import ANALYSIS_HORIZON, RiskSignal
from app.ai.schemas import AnalysisType, ModelAnalysisOutput, ModelRiskOutput

# Version of this policy; recorded in the audit trail with every analysis (Stage 9).
GUARDRAIL_VERSION = "2026.09-stage10"

# A marker that only appears in the system prompt; seeing it in output means the prompt leaked.
SYSTEM_PROMPT_CANARY = "HMS-AI-GUARD-7c1d"


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason_code: str | None = None
    message: str = ""


# --- normalization (Stage 9) ------------------------------------------------------------------

# Common Cyrillic/Greek letters that look like Latin ones (not a complete confusables table).
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
_SPACED_LETTERS = re.compile(r"\b(?:[A-Za-z] ){3,}[A-Za-z]\b")
_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def normalize(text: str) -> str:
    """Canonical form used for every pattern check (the original text is never modified)."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero-width, bidi, soft hyphen
    text = text.translate(_CONFUSABLES)
    return _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text)


def _decoded_payloads(text: str) -> str:
    decoded = []
    for token in _BASE64_TOKEN.findall(text):
        try:
            value = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if value.isprintable():
            decoded.append(value)
    return " ".join(decoded)


def _scan_text(text: str) -> str:
    normalized = normalize(text)
    extra = _decoded_payloads(normalized)
    return f"{normalized} {normalize(extra)}" if extra else normalized


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


# --- patterns ---------------------------------------------------------------------------------

PROMPT_INJECTION = [
    r"\bignore\b.{0,40}\b(instruction|rule|prompt|guardrail|polic)",
    r"\bdisregard\b.{0,40}\b(instruction|rule|prompt|above|previous)",
    r"\bforget\b.{0,30}\b(instruction|rule|everything|previous)",
    r"\byou are now\b", r"\bact as\b", r"\bpretend (to be|you)\b", r"\broleplay\b",
    r"\b(jailbreak|DAN mode|developer mode|god mode)\b",
    r"\bnew (instructions|rules|persona)\b", r"\boverride\b.{0,30}\b(safety|rules|restrictions|instructions)",
    r"</?(system|evidence|request|instructions|risk_context)>", r"\[\s*system\s*\]", r"^\s*system\s*:",
    r"\bwithout (any )?(restrictions|limits|guardrails|safety)\b",
    # Stage 9
    r"\bfrom now on\b", r"\b(unrestricted|unfiltered|uncensored)\b",
    r"(^|\n)[\s#>*_-]*(system|assistant|developer)\s*:",
    r"\b(ignora\w*|ignorez|ignoriere\w*|puuza|olvida\w*|oublie\w*)\b.{0,40}"
    r"\b(instruc\w*|anweisung\w*|maagizo|regla\w*|r[eè]gle\w*|consigne\w*)",
]
SYSTEM_PROMPT_EXTRACTION = [
    r"\b(system|initial|hidden|original)\s+(prompt|instructions|message)\b",
    r"\b(reveal|show|print|repeat|output|display|tell me|what are|leak)\b.{0,40}\b(your|the)\b.{0,20}"
    r"\b(prompt|instructions|rules|guidelines|configuration)\b",
    r"\bwhat were you told\b", r"\bverbatim\b.{0,30}\b(above|instructions|prompt)\b",
    # Stage 9
    r"\b(translate|summari[sz]e|paraphrase|encode|spell out|list)\b.{0,30}\b(your|the (system|initial|hidden|"
    r"original|above))\b.{0,20}\b(prompt|instructions|rules|guidelines)",
    r"\b(prompt|instructions|rules|guidelines)\b.{0,20}\byou (were|have been) (given|told)\b",
    r"\b(text|message|content|words)\s+(above|before this)\b", r"\bstarting with\b.{0,10}\byou are\b",
    r"hms-ai-guard",
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
    # Stage 9: diagnosis / prognosis
    r"\bdiagnose\b", r"\bwhat('s| is| are)\b.{0,10}\b(the|her|his|their|a)\b.{0,12}\b(diagnos[ie]s|prognosis)\b",
    r"\bwhat (disease|condition|illness|infection)s? (does|do|might|could|did)\b.{0,30}\bhave\b",
    r"\b(prognos\w*|life expectancy|surviv\w*|going to die)\b",
    r"\bwill (she|he|they|the patient)\b.{0,15}\b(die|recover|live|survive|deteriorate)\b",
    r"\bhow long\b.{0,30}\b(to live|left|survive)\b",
    # Stage 9: treatment choice, ordering, disposition, escalation
    r"\b(what|which)\b.{0,20}\b(antibiotic|antimalarial|drug|medication|medicine|treatment|therapy|fluid)s?\b.{0,30}"
    r"\b(should|to (use|give|start|prescribe)|is best|would you|do you recommend)\b",
    r"\b(request|arrange|send (for|off)|organi[sz]e)\b.{0,20}\b(an? |the )?(chest )?(x-?ray|ct|mri|scan|ultrasound|ecg|"
    r"echo\w*|culture|blood tests?|lab tests?|swab)\b",
    r"\b(ready|fit|safe|ok(ay)?|stable enough)\b.{0,20}\b(for )?(discharge|to go home|to be discharged|admission|"
    r"to be admitted)\b",
    r"\bshould\b.{0,25}\bbe (admitted|discharged|transferred)\b",
    r"\b(call|page|alert|notify|contact|summon)\b.{0,40}\b(team|doctor|nurse|icu|rapid response|consultant|family|"
    r"ambulance|on-call|specialist)\b",
    r"\bescalate\b.{0,40}\b(to|care|patient|him|her|them)\b",
]
CROSS_PATIENT = [r"\b(other|another|all|every|different|any other)\s+patients?\b", r"\blist (of )?patients\b",
                 r"\bcompare (him|her|them|this patient) (with|to)\b"]
# Stage 9: requests outside "analysis of this patient's records" even when clinical words appear.
OUT_OF_DOMAIN = [
    r"\b(write|generate|create|debug|fix)\b.{0,30}\b(code|script|program|function|query|regex|html|app)\b",
    r"\b(python|javascript|typescript|c\+\+|sql|html|css|regex|bash|powershell)\b",
    r"\b(vote|voting|election|president|politic\w*|government|religio\w*|stock market|bitcoin|crypto\w*|weather|"
    r"football|sports?|movie|recipe|capital of)\b",
    r"\b(empire|world war|dynasty|kingdom)\b",
    r"\b(joke|poem|song|story|essay|limerick|haiku|rap)\b",
    r"\bin general\b", r"\bgenerally\b", r"\b(explain|teach me|tell me)\b.{0,15}\bhow\b.{0,40}\bworks?\b",
    r"\bhow does\b.{0,40}\bwork\b",
    r"\bI (have|am having|'ve got|got) (a |an )?(headache|fever|pain|cough|rash|symptoms?|cold|flu)\b",
    r"\bwhat should I (take|do)\b",
    r"\b(my|our) (own )?(mother|father|mom|mum|dad|child|son|daughter|wife|husband|partner|friend|baby|brother|"
    r"sister|symptoms|health)\b",
]
# Stage 9: forward-looking periods other than the fixed four days.
_NUMBER_WORDS = r"\d+|few|several|two|three|five|six|seven|eight|nine|ten|fourteen|thirty|ninety"
HORIZON_TEXT = re.compile(
    rf"\b(?:next|coming|following|upcoming)\s+(?:(?P<n>{_NUMBER_WORDS})\s+)?(?P<unit>days?|weeks?|months?|years?|"
    rf"fortnight)\b|\blong[- ]term\b|\bover the (?:coming|next) (?:weeks|months|years)\b",
    re.I,
)
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


def _horizon_violation(text: str) -> bool:
    for match in HORIZON_TEXT.finditer(text):
        n, unit = match.group("n"), (match.group("unit") or "").lower()
        if unit.startswith("day") and n and n.lower() in {"4", "four"}:
            continue
        return True
    return False


def check_request(question: str | None, analysis_type: AnalysisType, *, patient_number: str,
                  patient_id: uuid.UUID) -> Verdict:
    if not question:
        return Verdict(True)
    text = _scan_text(question)
    if _any(SYSTEM_PROMPT_EXTRACTION, text):
        return Verdict(False, "system_prompt_extraction", "Requests for the assistant's instructions are not answered.")
    if _any(PROMPT_INJECTION, text):
        return Verdict(False, "prompt_injection", "The request tries to change the assistant's rules and was refused.")
    if _any(FORBIDDEN_ACTIONS, text):
        return Verdict(False, "forbidden_clinical_action",
                       "The assistant is read-only analysis: it cannot diagnose, prescribe, order, change records "
                       "or recommend treatment.")
    other_numbers = {n.upper() for n in PATIENT_NUMBER.findall(text)} - {patient_number.upper()}
    other_ids = {u.lower() for u in UUID_TEXT.findall(text)} - {str(patient_id)}
    if other_numbers or other_ids or _any(CROSS_PATIENT, text):
        return Verdict(False, "cross_patient_reference", "Only the selected patient can be analysed.")
    if _any(OUT_OF_DOMAIN, text) or (analysis_type == AnalysisType.QUESTION and not CLINICAL_VOCABULARY.search(text)):
        return Verdict(False, "out_of_domain", "The assistant only answers clinical questions about this patient.")
    if _horizon_violation(text):
        return Verdict(False, "horizon_out_of_scope",
                       "Risk analysis is limited to the next four days; other periods are not analysed.")
    return Verdict(True)


def check_requested_tools(requested: list[str] | None, allowed: frozenset[str]) -> Verdict:
    unknown = sorted(set(requested or []) - allowed)
    if unknown:
        return Verdict(False, "forbidden_tool", f"Unknown or forbidden tool(s): {', '.join(unknown)}.")
    return Verdict(True)


def evidence_flags(evidence: list[dict]) -> list[str]:
    text = _scan_text(json.dumps([e.get("data") for e in evidence], ensure_ascii=False))
    return ["evidence_contains_instruction_like_text"] if _any(EVIDENCE_INSTRUCTIONS, text) else []


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_model_output(raw: str, schema: type = ModelAnalysisOutput):
    """(validated output, None) or (None, error class name). `schema` selects the output contract."""
    text = raw.strip()
    fenced = _JSON_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return schema.model_validate(json.loads(text)), None
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        return None, type(exc).__name__


# --- output checks shared by all analysis types (Stage 9) -------------------------------------

# Treatment / ordering / disposition / escalation actions anywhere in an answer.
RISK_ACTIONS = [
    r"\b(start|begin|initiate|commence|give|administer|stop|withhold|increase|decrease)\b.{0,30}"
    r"\b(antibiotic\w*|antimalarial\w*|fluid\w*|insulin|oxygen|steroid\w*|analgesi\w*|paracetamol|"
    r"anticoagula\w*|diuretic\w*|vasopressor\w*|transfusion|medication|drug|dose|treatment|therapy)",
    r"\b(order(ing|ed)?|request(ing)?|send(ing)? (for|off))\b.{0,30}\b(test|lab\w*|culture|scan|x-?ray|imaging|"
    r"lactate|panel|count|film|smear|ecg|ultrasound|biopsy)",
    r"\bescalat\w* (care )?to (the )?(icu|hdu|intensive)",
    r"\btransfer (the patient |him |her |them )?to (the )?(icu|hdu)",
    # Stage 9
    r"\b(should|must|can|could|needs? to|ought to) be (admitted|discharged|transferred)\b",
    r"\b(call|page|alert|notify|summon)\b.{0,30}\b(team|doctor|nurse|icu|rapid response|consultant|on-call)\b",
]
# Prognosis claims (never allowed in any answer).
PROGNOSIS = [
    r"\bwill (definitely |certainly |likely |probably )?(develop|deteriorate|die|decompensate|crash|arrest|"
    r"become|need|require|suffer|progress|worsen)\b",
    r"\b\d{1,3}(\.\d+)?\s?% (chance|probability|risk|likelihood)\b",
    r"\b(predicts?|predicted|forecasts?) (that|a|an|the)\b",
]
# Mixed Latin + Cyrillic/Greek inside one word after normalization: deliberate obfuscation.
_MIXED_SCRIPT = re.compile(r"\b(?=\w*[A-Za-z])(?=\w*[Ͱ-ϿЀ-ӿ])\w+\b")

# Numbers with a clinical unit ("112 /min", "39.1 °C", "92%", "80/40 mmHg", "6.8 mmol/L").
MEASUREMENT = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?\s*"
    r"(°\s*[CF]\b|Cel\b|deg\s*[CF]\b|\[degF\]|bpm\b|beats?\s*/\s*min\b|breaths?\s*/\s*min\b|/\s*min\b|per minute\b|"
    r"%|mm\s*\[?Hg\]?|mg\s*/\s*dL\b|mmol\s*/\s*L\b|g\s*/\s*dL\b|g\s*/\s*L\b|kg\b|mg\b|mcg\b|ml\b|IU\b|units?\b|"
    r"[µu]mol\s*/\s*L\b|U\s*/\s*L\b|x\s*10\^?9\s*/\s*L\b)",
    re.I,
)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def evidence_numbers(evidence: list[dict], *extra_texts: str) -> set[float]:
    """Every number that appears in the evidence data (timestamps excluded) or in `extra_texts`."""
    numbers: set[float] = set()

    def walk(value, key: str = "") -> None:
        if isinstance(value, bool) or key.endswith("_at"):
            return
        if isinstance(value, (int, float)):
            numbers.add(float(value))
        elif isinstance(value, str):
            numbers.update(float(n) for n in _NUMBER.findall(value))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)

    for item in evidence:
        walk(item.get("data"))
    for text in extra_texts:
        numbers.update(float(n) for n in _NUMBER.findall(text))
    return numbers


def _ungrounded_measurement(text: str, allowed: set[float]) -> bool:
    for match in MEASUREMENT.finditer(text):
        for group in (match.group(1), match.group(2)):
            if group is not None and not any(abs(float(group) - n) < 0.051 for n in allowed):
                return True
    return False


def _common_output_checks(text: str, suggestions: list[str], *, patient_number: str,
                          allowed_numbers: set[float] | None) -> Verdict | None:
    """Checks every answer gets (Stage 9 shared). `text` is the raw joined answer text."""
    if _MIXED_SCRIPT.search(unicodedata.normalize("NFKC", text)):
        return Verdict(False, "obfuscated_text", "The response contained obfuscated (mixed-script) words.")
    text = normalize(text)
    suggestions = [normalize(s) for s in suggestions]
    if SYSTEM_PROMPT_CANARY.lower() in text.lower():
        return Verdict(False, "system_prompt_leak", "The response disclosed internal instructions.")
    if {n.upper() for n in PATIENT_NUMBER.findall(text)} - {patient_number.upper()}:
        return Verdict(False, "cross_patient_output", "The response referred to another patient.")
    if _any(OVERREACH, text) or _any(RISK_ACTIONS, text) or any(_any(FORBIDDEN_ACTIONS, s) for s in suggestions):
        return Verdict(False, "clinical_overreach",
                       "The response contained diagnosis, prescribing, ordering, disposition or treatment language.")
    if allowed_numbers is not None and _ungrounded_measurement(text, allowed_numbers):
        return Verdict(False, "ungrounded_measurement",
                       "The response quoted a measurement that is not present in the provided records.")
    return None


def _grounding_check(text: str, evidence: list[dict] | None, *extra_texts: str) -> Verdict | None:
    """Stage 10: named conditions, medications and clinical events must be traceable to the evidence.
    Runs last, so more specific policy violations keep their own reason codes."""
    if evidence is not None and ungrounded_claims(normalize(text), evidence, *extra_texts):
        return Verdict(False, "ungrounded_clinical_claim",
                       "The response named a condition, medication or clinical event that is not in the provided "
                       "records.")
    return None


def check_output(output: ModelAnalysisOutput, *, analysis_type: AnalysisType, patient_number: str,
                 evidence_ids: set[str], evidence: list[dict] | None = None) -> Verdict:
    """`evidence` (Stage 9) enables the measurement-grounding check."""
    if output.patient_reference.upper() != patient_number.upper():
        return Verdict(False, "patient_mismatch", "The model referred to a different patient.")
    if output.analysis_type != analysis_type:
        return Verdict(False, "analysis_type_mismatch", "The model answered a different analysis type.")
    cited = {c.source_id for c in output.evidence}
    if not cited <= evidence_ids:
        return Verdict(False, "unsupported_citation", "The model cited sources that were not provided.")
    text = " ".join([output.analysis, *output.review_suggestions, *output.limitations, output.abstain_reason or ""])
    common = _common_output_checks(text, output.review_suggestions, patient_number=patient_number,
                                   allowed_numbers=evidence_numbers(evidence) if evidence is not None else None)
    if common:
        return common
    if _any(PROGNOSIS, normalize(text)):
        return Verdict(False, "overconfident_language", "The response stated a prognosis or prediction.")
    return _grounding_check(text, evidence) or Verdict(True)


# --- Stage 8: four-day risk output ------------------------------------------------------------

# Certainty / prediction / diagnosis claims. A potential-risk analysis never states outcomes.
CERTAINTY = PROGNOSIS + [
    r"\b(definitely|certainly|undoubtedly|guaranteed|without (a )?doubt|inevitabl\w*|certain to)\b",
    r"\b(is|are|has been|have been) confirmed\b", r"\bconfirm(s|ed)? (the |a )?(diagnosis|sepsis|infection)\b",
    r"\b(has|have|is suffering from|is developing|is in|diagnosis of) (sepsis|septic shock|shock|pneumonia|malaria|"
    r"meningitis|an? (infection|stroke|heart attack|myocardial infarction|pulmonary embolism|dvt))\b",
]
HEDGED = re.compile(r"\b(potential\w*|possib\w*|may|might|could|suggest\w*|warrant\w*|consider\w*|concern\w*|"
                    r"review\w*|uncertain\w*)\b", re.I)
REVIEW_ORIENTED = re.compile(r"\b(review\w*|consider\w*|verif\w*|check\w*|confirm\w*|re-?assess\w*|monitor\w*|"
                             r"clinician\w*|clinical team|warrant\w*|evaluat\w*|re-?measur\w*)\b", re.I)
_VALIDATED = re.compile(r"\b(clinically )?validated\b", re.I)
_NEGATION = re.compile(r"\b(not|never|no|without)\b", re.I)


def _claims_validation(text: str) -> bool:
    """True if the text claims validation ("a validated score"), not when it denies it ("not validated")."""
    for match in _VALIDATED.finditer(text):
        if not _NEGATION.search(text[max(0, match.start() - 25):match.start()]):
            return True
    return False


def check_risk_output(output: ModelRiskOutput, *, patient_number: str, reference_at: datetime,
                      signals: list[RiskSignal], evidence_ids: set[str], evidence: list[dict] | None = None) -> Verdict:
    """Semantic validation of a FOUR_DAY_RISK answer (the schema already checked its structure).
    `evidence` (Stage 9) enables the measurement-grounding check."""
    if output.patient_reference.upper() != patient_number.upper():
        return Verdict(False, "patient_mismatch", "The model referred to a different patient.")
    if not (output.reference_at == reference_at and output.horizon_start == reference_at
            and output.horizon_end == reference_at + ANALYSIS_HORIZON):
        return Verdict(False, "horizon_mismatch", "The model changed the reference time or the four-day horizon.")
    expected = {s.signal_id: s for s in signals}
    returned = {s.signal_id: s for s in output.risk_signals}
    if set(returned) - set(expected):
        return Verdict(False, "unsupported_risk_signal", "The model added risk signals the rule layer did not produce.")
    if output.status == "ANALYSIS" and set(expected) - set(returned):
        return Verdict(False, "risk_signal_omitted", "The model omitted computed risk signals.")
    for signal_id, signal in returned.items():
        rule = expected[signal_id]
        if signal.category != rule.category or signal.priority != rule.priority:
            return Verdict(False, "risk_signal_altered", "The model changed a signal's category or priority.")
        if not set(signal.evidence) <= set(rule.evidence):
            return Verdict(False, "unsupported_citation", "A signal cited records outside its supporting evidence.")
        if not HEDGED.search(normalize(signal.explanation)):
            return Verdict(False, "unhedged_risk_language",
                           "Signal explanations must be phrased as potential concerns for review.")
    cited = {c.source_id for c in output.evidence} | {e for t in output.observed_trends for e in t.evidence}
    if not cited <= evidence_ids:
        return Verdict(False, "unsupported_citation", "The model cited sources that were not provided.")
    raw_text = " ".join([output.summary, *(s.explanation for s in output.risk_signals),
                         *(t.description for t in output.observed_trends), *output.limitations,
                         *output.precautionary_suggestions, output.abstain_reason or ""])
    signal_texts = tuple(f"{s.title} {s.detail}" for s in signals)
    allowed = evidence_numbers(evidence, *signal_texts) if evidence is not None else None
    common = _common_output_checks(raw_text, output.precautionary_suggestions, patient_number=patient_number,
                                   allowed_numbers=allowed)
    if common:
        return common
    text = normalize(raw_text)
    if _any(CERTAINTY, text) or _claims_validation(text):
        return Verdict(False, "overconfident_risk_language",
                       "The response stated certainty, predictions, diagnoses or validation it cannot support.")
    if _horizon_violation(text):
        return Verdict(False, "horizon_mismatch", "The response discussed a period other than the four-day horizon.")
    if not all(REVIEW_ORIENTED.search(normalize(s)) for s in output.precautionary_suggestions):
        return Verdict(False, "non_review_suggestion", "Precautionary suggestions must be review-oriented.")
    return _grounding_check(raw_text, evidence, *signal_texts) or Verdict(True)
