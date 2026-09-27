"""Clinical-claim grounding for AI output (Stage 10; hardened in the final Stage 10 grounding pass).

Rule: every clinical claim in a model answer must be traceable to the supplied patient evidence.
Otherwise the answer is rejected (`ungrounded_clinical_claim`) and the assistant abstains
(abstention always remains available to the model and to the pipeline).

Recognised claims (deterministic, inspectable):
1. Named entities - conditions/diagnoses, medications (names, classes, drug-name suffixes) and
   clinical events (admission, ICU, surgery, ...). Grounded only if the term occurs in the evidence text.
2. Clinical labels derived from measurements - tachycardia, pyrexia, hypoxaemia, anaemia, ... A
   measurement being present is NOT enough: the label is grounded only if the evidence text itself uses it,
   or a recorded value meets the label's explicit definition in `LABEL_RULES`. Stronger labels that have no
   rule (e.g. "hyperthermia", "hyperpyrexia") must appear in the evidence text.
3. Clinical context details - oxygen support ("room air", "supplemental oxygen", ...), mental state,
   symptoms, circumstances ("at rest", "post-operative", ...). Grounded only if they occur in the evidence
   text. A sentence that explicitly says the detail is missing/undocumented/unknown, or asks
   "whether"/"if", makes no claim and is allowed; any other sentence mentioning the detail is a claim.

`LABEL_RULES` are conventional wording definitions used only to check that a label matches a recorded
value. They are configurable, they are NOT risk thresholds, and they are not clinically validated.

Limitation: claims expressed in words outside these lists (and without a recognised suffix) are not
detected, and a grounded term can still appear in an incorrect sentence. Human review remains mandatory.
"""

import re
from dataclasses import dataclass

from app.ai.risk_signals import _canonical  # unit normalisation shared with the risk engine (°F -> °C, mg/dL -> mmol/L)


@dataclass(frozen=True)
class LabelRule:
    """A label is supported when a recorded value satisfies `op value` (observations: canonical units)."""

    codes: tuple[str, ...] = ()      # observation codes
    op: str = ""
    value: float = 0.0
    analytes: tuple[str, ...] = ()   # lab analyte names (lower-case substrings) flagged in `direction`
    direction: str = ""              # "LOW" or "HIGH" (interpretation flag or outside the reference range)


# Label stem -> definition. Conventional definitions (configurable), not validated risk thresholds.
LABEL_RULES: dict[str, LabelRule] = {
    "tachycard": LabelRule(("heart_rate",), ">", 100), "bradycard": LabelRule(("heart_rate",), "<", 60),
    "tachypn": LabelRule(("respiratory_rate",), ">", 20), "bradypn": LabelRule(("respiratory_rate",), "<", 12),
    "hypoxaem": LabelRule(("oxygen_saturation",), "<", 95), "hypoxem": LabelRule(("oxygen_saturation",), "<", 95),
    "hypoxi": LabelRule(("oxygen_saturation",), "<", 95), "desaturat": LabelRule(("oxygen_saturation",), "<", 95),
    "fever": LabelRule(("body_temperature",), ">=", 38.0), "febrile": LabelRule(("body_temperature",), ">=", 38.0),
    "pyrexi": LabelRule(("body_temperature",), ">=", 38.0), "hypothermi": LabelRule(("body_temperature",), "<", 35.0),
    "hypertensi": LabelRule(("systolic_blood_pressure",), ">=", 140),
    "hypotensi": LabelRule(("systolic_blood_pressure",), "<", 90),
    "hyperglyc": LabelRule(("blood_glucose",), ">", 11.0), "hypoglyc": LabelRule(("blood_glucose",), "<", 3.9),
    "anaemi": LabelRule(analytes=("hemoglobin", "haemoglobin"), direction="LOW"),
    "anemi": LabelRule(analytes=("hemoglobin", "haemoglobin"), direction="LOW"),
    "hyperkal": LabelRule(analytes=("potassium",), direction="HIGH"),
    "hypokal": LabelRule(analytes=("potassium",), direction="LOW"),
    "hypernatr": LabelRule(analytes=("sodium",), direction="HIGH"),
    "hyponatr": LabelRule(analytes=("sodium",), direction="LOW"),
}
# Diastolic pressure also supports "hypertension" (>= 90 mmHg).
_EXTRA_LABEL_RULES = {"hypertensi": LabelRule(("diastolic_blood_pressure",), ">=", 90)}

CONDITIONS = (
    "diabetes", "diabetic", "asthma", "copd", "emphysema", "pneumonia", "tuberculosis", "malaria", "typhoid",
    "cholera", "dengue", "hiv", "sepsis", "septic", "meningitis", "stroke", "myocardial infarction",
    "heart attack", "heart failure", "cardiac failure", "angina", "arrhythmia", "atrial fibrillation", "cancer",
    "malignan", "tumour", "tumor", "leukaemia", "leukemia", "lymphoma", "kidney disease", "renal failure",
    "kidney injury", "ckd", "dvt", "pulmonary embolism", "embolism", "epilep", "dementia", "depression",
    "schizophren", "bipolar", "obesity", "obese", "covid", "influenza", "measles", "pregnan", "gout",
    "sickle cell", "peptic ulcer", "ulcer", "dehydrat", "shock", "delirium", "coma", "cirrhosis", "jaundice",
    "hypothyroid", "hyperthyroid", "thyroid", "infarct", "ischaemi", "ischemi", "haemorrhag", "hemorrhag",
    "fracture", "burn", "trauma", "overdose", "poisoning", "anaphyla",
    # stronger labels without a LABEL_RULES definition: only if the record itself uses them
    "hyperthermi", "hyperpyrexi", "respiratory failure", "respiratory distress", "hypoperfusion",
)
MEDICATIONS = (
    "paracetamol", "acetaminophen", "ibuprofen", "aspirin", "diclofenac", "morphine", "tramadol", "codeine",
    "penicillin", "ampicillin", "amoxicillin", "ceftriaxone", "cefuroxime", "cefalexin", "cefotaxime",
    "ceftazidime", "cefazolin", "azithromycin", "erythromycin", "ciprofloxacin",
    "metronidazole", "fluconazole", "cotrimoxazole", "co-trimoxazole", "doxycycline", "gentamicin",
    "vancomycin", "artemether", "lumefantrine", "artesunate", "quinine", "chloroquine", "primaquine",
    "metformin", "glibenclamide", "insulin", "amlodipine", "nifedipine", "lisinopril", "enalapril",
    "captopril", "losartan", "atenolol", "propranolol", "furosemide", "hydrochlorothiazide", "spironolactone",
    "atorvastatin", "simvastatin", "warfarin", "heparin", "enoxaparin", "rivaroxaban", "clopidogrel",
    "salbutamol", "prednisolone", "prednisone", "dexamethasone", "hydrocortisone", "omeprazole", "ranitidine",
    "ondansetron", "metoclopramide", "diazepam", "lorazepam", "phenytoin", "carbamazepine", "valproate",
    "levetiracetam", "haloperidol", "fluoxetine", "amitriptyline", "tenofovir", "lamivudine", "efavirenz",
    "dolutegravir", "zidovudine", "isoniazid", "rifampicin", "pyrazinamide", "ethambutol", "oxytocin",
    # medication classes
    "antibiotic", "antimalarial", "anticoagula", "antihypertensive", "antiretroviral", "opioid", "steroid",
    "chemotherap", "diuretic", "vasopressor", "sedative", "antiepilep", "anticonvuls", "antipsychotic",
    "antidepressant", "bronchodilator", "inhaler", "thrombolys",
)
EVENTS = (
    "admitted", "admission to", "icu", "intensive care", "hdu", "high dependency", "surgery", "surgical",
    "operation", "operated", "intubat", "ventilat", "dialysis", "transfus", "resuscitat", "cardiac arrest",
    "code blue", "seizure", "convuls", "had a fall", "sustained a fall", "died", "death", "deceased",
    "discharged", "transferred", "readmi", "biopsy", "endoscop", "catheteri",
)
# Clinical context details: oxygen support, circumstances, mental state, symptoms and signs.
CONTEXT = (
    "room air", "supplemental oxygen", "on oxygen", "oxygen therapy", "nasal cannula", "nasal prong", "face mask",
    "non-rebreather", "high-flow", "high flow", "cpap", "bipap", "at rest", "on exertion", "post-operative",
    "postoperative", "sedated", "sedation", "fasting", "bedbound", "bed-bound", "immobile", "smoker", "smoking",
    "alcohol", "travel", "sick contact", "letharg", "confus", "drowsy", "agitat", "distress", "diaphore",
    "cyanos", "cyanotic", "pallor", "dyspn", "shortness of breath", "breathless", "chest pain", "headache",
    "vomit", "diarrh", "rash", "wheez", "crackles", "oedema", "edema", "unresponsive", "altered mental",
    "gcs", "rigor", "chills", "night sweats", "weight loss", "cough",
)
# A sentence with these words states that information is missing, or asks for it to be checked: no claim.
_NO_CLAIM = re.compile(
    r"\b(not (documented|recorded|available|stated|specified|reported|known)|no (record|documentation|data)|"
    r"undocumented|absence of|missing|unknown|whether|if)\b", re.I)

_TERMS = tuple(sorted({*CONDITIONS, *MEDICATIONS, *EVENTS}, key=len, reverse=True))
_TERMS_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _TERMS) + r")\w*", re.I)
_CONTEXT_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(CONTEXT, key=len, reverse=True)) + r")\w*", re.I)
_LABEL_RE = re.compile(r"\b(" + "|".join(sorted(LABEL_RULES, key=len, reverse=True)) + r")\w*", re.I)
_MEDICATION_SUFFIX = re.compile(
    r"\b\w{3,}(cillin|mycin|micin|floxacin|cycline|azole|prazole|tidine|formin|gliptin|dipine|pril|sartan|olol|"
    r"statin|parin|xaban|azepam|oxetine|setron|thiazide|semide|vudine|gravir|tegravir|navir|previr|umab|imab|"
    r"ximab|zumab)\b", re.I)
_CONDITION_SUFFIX = re.compile(r"\b\w{4,}(itis|osis|aemia|emia|oma|pathy|algia|plegia|ectomy|otomy|oscopy)\b", re.I)
_ORDINARY_WORDS = {"diagnosis", "prognosis", "empathy", "sympathy", "telepathy", "nostalgia", "academia",
                   "aroma", "diploma", "hypnosis", "osmosis", "symptoma"}
_SENTENCE = re.compile(r"[^.;!?\n]+[.;!?]?")


def clinical_terms(text: str) -> set[tuple[str, str]]:
    """(kind, matched word) for every clinical claim term recognised in `text`.
    kind is 'label:<stem>', 'term:<stem>', 'context:<stem>' or 'word:<word>'."""
    found: set[tuple[str, str]] = set()
    label_spans = []
    for m in _LABEL_RE.finditer(text):
        found.add(("label:" + m.group(1).lower(), m.group(0).lower()))
        label_spans.append(m.span())

    def in_label(start: int) -> bool:
        return any(a <= start < b for a, b in label_spans)

    for m in _TERMS_RE.finditer(text):
        if not in_label(m.start()):
            found.add(("term:" + m.group(1).lower(), m.group(0).lower()))
    for sentence in _SENTENCE.finditer(text):
        if _NO_CLAIM.search(sentence.group(0)):
            continue  # "oxygen support is not documented", "verify whether ... on room air"
        for m in _CONTEXT_RE.finditer(sentence.group(0)):
            found.add(("context:" + m.group(1).lower(), m.group(0).lower()))
    for regex in (_MEDICATION_SUFFIX, _CONDITION_SUFFIX):
        for m in regex.finditer(text):
            word = m.group(0).lower()
            if word not in _ORDINARY_WORDS and not in_label(m.start()):
                found.add(("word:" + word, word))
    return found


def evidence_corpus(evidence: list[dict], *extra_texts: str) -> str:
    """Lower-case text of every value in the evidence (plus `extra_texts`)."""
    parts: list[str] = []

    def walk(value) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for item in evidence:
        walk(item.get("data") or {})
    parts.extend(extra_texts)
    return " ".join(parts).lower()


def _compare(value: float, op: str, limit: float) -> bool:
    return {">": value > limit, ">=": value >= limit, "<": value < limit, "<=": value <= limit}[op]


def label_supported(stem: str, evidence: list[dict]) -> bool:
    """True if a recorded value meets the label's definition in LABEL_RULES."""
    rules = [LABEL_RULES[stem]] + ([_EXTRA_LABEL_RULES[stem]] if stem in _EXTRA_LABEL_RULES else [])
    for item in evidence:
        data = item.get("data") or {}
        for rule in rules:
            if item.get("type") == "observation" and data.get("code") in rule.codes:
                value = _canonical(data["code"], data.get("value"), data.get("unit"))
                if value is not None and _compare(value, rule.op, rule.value):
                    return True
            if item.get("type") == "lab_result" and rule.analytes and any(
                    a in str(data.get("analyte") or "").lower() for a in rule.analytes):
                flag = str(data.get("interpretation") or "")
                value, low, high = data.get("value"), data.get("reference_low"), data.get("reference_high")
                numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                if rule.direction == "LOW" and (flag in {"LOW", "CRITICAL_LOW"} or (
                        numeric and low is not None and value < low)):
                    return True
                if rule.direction == "HIGH" and (flag in {"HIGH", "CRITICAL_HIGH"} or (
                        numeric and high is not None and value > high)):
                    return True
    return False


def ungrounded_claims(text: str, evidence: list[dict], *extra_texts: str) -> list[str]:
    """Clinical claim terms in `text` that the evidence does not support (empty list = grounded)."""
    corpus = evidence_corpus(evidence, *extra_texts)
    missing = []
    for kind, word in sorted(clinical_terms(text)):
        category, stem = kind.split(":", 1)
        if stem in corpus:
            continue  # the record itself uses the term
        if category == "label" and label_supported(stem, evidence):
            continue
        missing.append(word)
    return missing


__all__ = ["CONTEXT", "LABEL_RULES", "LabelRule", "clinical_terms", "evidence_corpus", "label_supported",
           "ungrounded_claims"]
