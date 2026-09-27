"""Deterministic potential-risk signal layer for the four-day risk analysis (Stage 8).

The LLM is NOT the risk predictor. Signals are computed here, in plain inspectable code, from the
same evidence items the model is shown; the model may only explain them (and must return every
one unchanged - see guardrails.check_risk_output).

IMPORTANT - prototype logic, NOT clinically validated
-----------------------------------------------------
The only rule set shipped, "demo-v1", uses illustrative thresholds chosen for demonstration and
testing. They are not derived from, calibrated against, or validated by any clinical study or
early-warning score, and must not be presented as such. Every output carries `validated=False`
and the notice below. A validated rule set (or a validated model) can be plugged in by adding a
`RuleSet` to `RULESETS` and selecting it with AI_RISK_RULESET - nothing else changes.

Rules (demo-v1):
    VITAL_SIGN        latest reading of a catalog vital outside an illustrative band
    VITAL_TREND       >= 3 readings of one vital moving steadily in one direction by >= a delta
    LAB_RESULT        released lab result flagged abnormal / outside its own reference range
    MEDICATION_SAFETY active allergy substance named in an active/on-hold prescription item
    DATA_CONFLICT     two readings of one vital taken close together that disagree strongly
Every signal carries the source_ids of the exact records it came from. Missing data is never a
signal (it has no source record); it is reported as a data gap instead.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

# Fixed by requirement. Not configurable, not chosen by the model.
ANALYSIS_HORIZON_DAYS = 4
ANALYSIS_HORIZON = timedelta(days=ANALYSIS_HORIZON_DAYS)

UNVALIDATED_NOTICE = (
    "Signals come from a demonstration rule set with illustrative thresholds. It is NOT clinically "
    "validated and does not predict outcomes; signals only indicate records that may warrant clinical review."
)


class SignalCategory(StrEnum):
    VITAL_SIGN = "VITAL_SIGN"
    VITAL_TREND = "VITAL_TREND"
    LAB_RESULT = "LAB_RESULT"
    MEDICATION_SAFETY = "MEDICATION_SAFETY"
    DATA_CONFLICT = "DATA_CONFLICT"


class ReviewPriority(StrEnum):
    """Suggested priority for clinical REVIEW - not a clinical severity or acuity score."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


PRIORITY_RANK = {ReviewPriority.LOW: 0, ReviewPriority.MODERATE: 1, ReviewPriority.HIGH: 2}


@dataclass(frozen=True)
class Band:
    """Illustrative band for one vital: readings <= low or >= high produce a signal;
    beyond the *_high_priority limits the review priority is HIGH, otherwise MODERATE."""

    low: float | None
    high: float | None
    low_high_priority: float | None = None
    high_high_priority: float | None = None


@dataclass(frozen=True)
class Trend:
    direction: int  # +1 rising is of interest, -1 falling is of interest
    min_change: float


@dataclass(frozen=True)
class Conflict:
    max_gap_minutes: int
    min_difference: float


@dataclass(frozen=True)
class RuleSet:
    ruleset_id: str
    version: str
    validated: bool
    description: str
    bands: dict[str, Band]
    trends: dict[str, Trend]
    conflicts: dict[str, Conflict]
    trend_min_readings: int = 3
    required_observation_codes: tuple[str, ...] = ()


# Values are in the canonical unit of each code (temperature in Cel, glucose in mmol/L).
DEMO_V1 = RuleSet(
    ruleset_id="demo-v1",
    version="1.0.0",
    validated=False,
    description="Illustrative demonstration thresholds (NOT clinically validated).",
    bands={
        "body_temperature": Band(low=35.5, high=38.0, low_high_priority=35.0, high_high_priority=39.5),
        "heart_rate": Band(low=50, high=110, low_high_priority=40, high_high_priority=130),
        "respiratory_rate": Band(low=10, high=24, low_high_priority=8, high_high_priority=30),
        "oxygen_saturation": Band(low=93, high=None, low_high_priority=90),
        "systolic_blood_pressure": Band(low=95, high=180, low_high_priority=85, high_high_priority=210),
        "diastolic_blood_pressure": Band(low=None, high=110, high_high_priority=125),
        "blood_glucose": Band(low=3.9, high=16.7, low_high_priority=3.0, high_high_priority=25.0),
    },
    trends={
        "body_temperature": Trend(+1, 1.0),
        "heart_rate": Trend(+1, 20),
        "respiratory_rate": Trend(+1, 6),
        "oxygen_saturation": Trend(-1, 4),
        "systolic_blood_pressure": Trend(-1, 25),
    },
    conflicts={
        "body_temperature": Conflict(30, 1.5),
        "heart_rate": Conflict(30, 40),
        "oxygen_saturation": Conflict(30, 8),
        "systolic_blood_pressure": Conflict(30, 40),
        "respiratory_rate": Conflict(30, 12),
    },
    required_observation_codes=("body_temperature", "heart_rate", "respiratory_rate", "oxygen_saturation",
                                "systolic_blood_pressure"),
)

RULESETS: dict[str, RuleSet] = {DEMO_V1.ruleset_id: DEMO_V1}


@dataclass(frozen=True)
class RiskSignal:
    signal_id: str
    rule_id: str
    category: SignalCategory
    priority: ReviewPriority
    title: str
    detail: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"signal_id": self.signal_id, "rule_id": self.rule_id, "category": self.category.value,
                "priority": self.priority.value, "title": self.title, "detail": self.detail,
                "evidence": list(self.evidence)}


@dataclass
class SignalReport:
    ruleset: RuleSet
    signals: list[RiskSignal] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    observation_count: int = 0


# --- helpers ---------------------------------------------------------------------------------


def _canonical(code: str, value: Any, unit: str | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if code == "body_temperature" and unit == "[degF]":
        return round((value - 32) * 5 / 9, 2)
    if code == "blood_glucose" and unit == "mg/dL":
        return round(value / 18.0, 2)
    return float(value)


def _when(item: dict) -> datetime:
    return datetime.fromisoformat(item["occurred_at"])


def _fmt(value: float) -> str:
    return f"{value:g}"


def _vital_series(evidence: list[dict]) -> dict[str, list[tuple[datetime, float, dict]]]:
    series: dict[str, list[tuple[datetime, float, dict]]] = {}
    for item in evidence:
        if item["type"] != "observation":
            continue
        data = item["data"]
        value = _canonical(data["code"], data.get("value"), data.get("unit"))
        if value is not None:
            series.setdefault(data["code"], []).append((_when(item), value, item))
    for readings in series.values():
        readings.sort(key=lambda r: (r[0], r[2]["source_id"]))
    return series


# --- rules -----------------------------------------------------------------------------------


def _band_rule(rules: RuleSet, series) -> list[tuple]:
    found = []
    for code, band in rules.bands.items():
        if code not in series:
            continue
        at, value, item = series[code][-1]  # latest reading only
        display = item["data"].get("display") or code
        if band.high is not None and value >= band.high:
            high = band.high_high_priority is not None and value >= band.high_high_priority
            found.append((f"vital_high.{code}", SignalCategory.VITAL_SIGN,
                          ReviewPriority.HIGH if high else ReviewPriority.MODERATE,
                          f"{display} above the illustrative band",
                          f"Latest {display} {_fmt(value)} is at or above the demo threshold {_fmt(band.high)}.",
                          (item["source_id"],)))
        elif band.low is not None and value <= band.low:
            high = band.low_high_priority is not None and value <= band.low_high_priority
            found.append((f"vital_low.{code}", SignalCategory.VITAL_SIGN,
                          ReviewPriority.HIGH if high else ReviewPriority.MODERATE,
                          f"{display} below the illustrative band",
                          f"Latest {display} {_fmt(value)} is at or below the demo threshold {_fmt(band.low)}.",
                          (item["source_id"],)))
    return found


def _trend_rule(rules: RuleSet, series) -> list[tuple]:
    found = []
    for code, trend in rules.trends.items():
        readings = series.get(code, [])
        if len(readings) < rules.trend_min_readings:
            continue
        values = [v for _, v, _ in readings]
        steps = [b - a for a, b in zip(values, values[1:])]
        monotonic = all(s * trend.direction >= 0 for s in steps)
        change = (values[-1] - values[0]) * trend.direction
        if monotonic and change >= trend.min_change:
            display = readings[-1][2]["data"].get("display") or code
            word = "rising" if trend.direction > 0 else "falling"
            found.append((f"trend.{code}", SignalCategory.VITAL_TREND, ReviewPriority.MODERATE,
                          f"{display} {word} across recent readings",
                          f"{display} moved from {_fmt(values[0])} to {_fmt(values[-1])} over "
                          f"{len(readings)} readings (demo change threshold {_fmt(trend.min_change)}).",
                          tuple(r[2]["source_id"] for r in readings)))
    return found


def _conflict_rule(rules: RuleSet, series) -> list[tuple]:
    found = []
    for code, conflict in rules.conflicts.items():
        readings = series.get(code, [])
        for (t1, v1, i1), (t2, v2, i2) in zip(readings, readings[1:]):
            if (t2 - t1) <= timedelta(minutes=conflict.max_gap_minutes) and abs(v2 - v1) >= conflict.min_difference:
                display = i2["data"].get("display") or code
                found.append((f"conflict.{code}", SignalCategory.DATA_CONFLICT, ReviewPriority.MODERATE,
                              f"Conflicting {display} readings",
                              f"Two {display} readings {round((t2 - t1).total_seconds() / 60)} min apart differ by "
                              f"{_fmt(abs(v2 - v1))} ({_fmt(v1)} vs {_fmt(v2)}); one may be erroneous.",
                              (i1["source_id"], i2["source_id"])))
                break  # one conflict signal per code
    return found


ABNORMAL_INTERPRETATIONS = {"LOW": ReviewPriority.MODERATE, "HIGH": ReviewPriority.MODERATE,
                            "ABNORMAL": ReviewPriority.MODERATE, "CRITICAL_LOW": ReviewPriority.HIGH,
                            "CRITICAL_HIGH": ReviewPriority.HIGH}


def _lab_rule(evidence: list[dict]) -> list[tuple]:
    found = []
    for item in evidence:
        if item["type"] != "lab_result":
            continue
        data = item["data"]
        priority = ABNORMAL_INTERPRETATIONS.get(data.get("interpretation") or "")
        value, low, high = data.get("value"), data.get("reference_low"), data.get("reference_high")
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        outside = numeric and ((low is not None and value < low) or (high is not None and value > high))
        if priority is None and outside:
            priority = ReviewPriority.MODERATE
        if priority is None:
            continue
        flag = data.get("interpretation") or "outside the reported reference range"
        found.append((f"lab_abnormal.{item['source_id'].split(':', 1)[1][:8]}", SignalCategory.LAB_RESULT, priority,
                      f"{data.get('analyte')} result flagged {flag}",
                      f"Released result {data.get('analyte')} = {value} {data.get('unit') or ''} "
                      f"(reference {low if low is not None else '-'}-{high if high is not None else '-'}; "
                      f"interpretation {data.get('interpretation') or 'none'}).".replace("  ", " "),
                      (item["source_id"],)))
    return found


def _allergy_medication_rule(evidence: list[dict]) -> list[tuple]:
    allergies = [e for e in evidence if e["type"] == "allergy" and e["data"].get("status") == "ACTIVE"]
    prescriptions = [e for e in evidence if e["type"] == "prescription"
                     and e["data"].get("status") in {"ACTIVE", "ON_HOLD"}]
    found = []
    for allergy in allergies:
        substance = (allergy["data"].get("substance") or "").strip().lower()
        if len(substance) < 3:
            continue
        for rx in prescriptions:
            names = [i["medicine"] for i in rx["data"].get("items", []) if substance in i["medicine"].lower()]
            if names:
                found.append((f"allergy_medication.{allergy['source_id'].split(':', 1)[1][:8]}",
                              SignalCategory.MEDICATION_SAFETY, ReviewPriority.HIGH,
                              "Documented allergy matches a current prescription item",
                              f"Active allergy to '{allergy['data'].get('substance')}' and a current prescription "
                              f"item named '{names[0]}' (text match only).",
                              (allergy["source_id"], rx["source_id"])))
    return found


def compute_signals(evidence: list[dict], ruleset_id: str) -> SignalReport:
    """Pure function of the evidence items: same evidence -> same signals."""
    rules = RULESETS[ruleset_id]
    series = _vital_series(evidence)
    raw = (_band_rule(rules, series) + _trend_rule(rules, series) + _conflict_rule(rules, series)
           + _lab_rule(evidence) + _allergy_medication_rule(evidence))
    raw.sort(key=lambda r: (-PRIORITY_RANK[r[2]], r[1].value, r[0]))
    report = SignalReport(ruleset=rules, observation_count=sum(len(v) for v in series.values()))
    report.signals = [RiskSignal(f"SIG-{n:02d}", f"{rules.ruleset_id}.{rule_id}", category, priority, title, detail,
                                 evidence_ids)
                      for n, (rule_id, category, priority, title, detail, evidence_ids) in enumerate(raw, start=1)]
    missing = [code for code in rules.required_observation_codes if code not in series]
    if missing:
        report.data_gaps.append("No reading in the evidence window for: " + ", ".join(missing) + ".")
    if not any(e["type"] == "lab_result" for e in evidence):
        report.data_gaps.append("No released lab results in the evidence window.")
    return report


def max_priority(signals: list[RiskSignal]) -> ReviewPriority | None:
    return max((s.priority for s in signals), key=PRIORITY_RANK.__getitem__, default=None)


__all__ = ["ANALYSIS_HORIZON", "ANALYSIS_HORIZON_DAYS", "DEMO_V1", "RULESETS", "ReviewPriority", "RiskSignal",
           "RuleSet", "SignalCategory", "SignalReport", "UNVALIDATED_NOTICE", "compute_signals", "max_priority"]
