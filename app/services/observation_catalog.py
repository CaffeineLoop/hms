"""Catalog of well-known observation codes (vital signs and common measurements).

For a catalog code the unit must be one of the listed UCUM units and the value must be
physiologically possible (a sanity bound to catch typos and unit mix-ups, not a normal
range). The LOINC coding is filled in automatically, matching what Synthea/FHIR
exports use, so future imports map onto the same codes.

Codes outside the catalog are accepted (the model is generic) but must supply a
`display` name; no unit or range rules are applied to them.
"""

from dataclasses import dataclass

LOINC = "http://loinc.org"


@dataclass(frozen=True)
class ObservationDefinition:
    display: str
    loinc: str
    units: dict[str, tuple[float, float]]  # UCUM unit -> inclusive plausible range


CATALOG: dict[str, ObservationDefinition] = {
    "body_temperature": ObservationDefinition("Body temperature", "8310-5", {"Cel": (25, 45), "[degF]": (77, 113)}),
    "heart_rate": ObservationDefinition("Heart rate", "8867-4", {"/min": (0, 300)}),
    "respiratory_rate": ObservationDefinition("Respiratory rate", "9279-1", {"/min": (0, 150)}),
    "oxygen_saturation": ObservationDefinition("Oxygen saturation (SpO2)", "59408-5", {"%": (0, 100)}),
    "systolic_blood_pressure": ObservationDefinition("Systolic blood pressure", "8480-6", {"mm[Hg]": (0, 350)}),
    "diastolic_blood_pressure": ObservationDefinition("Diastolic blood pressure", "8462-4", {"mm[Hg]": (0, 250)}),
    "body_weight": ObservationDefinition("Body weight", "29463-7", {"kg": (0, 700), "[lb_av]": (0, 1550)}),
    "body_height": ObservationDefinition("Body height", "8302-2", {"cm": (0, 300)}),
    "blood_glucose": ObservationDefinition("Glucose [Mass/volume] in Blood", "2339-0", {"mg/dL": (0, 2000), "mmol/L": (0, 120)}),
}


@dataclass(frozen=True)
class ResolvedObservation:
    display: str
    code_system: str | None
    system_code: str | None


def validate_observation(
    *, code: str, value: float | None, unit: str | None, display: str | None
) -> ResolvedObservation:
    """Raise ValueError if the observation breaks catalog rules; return display/coding to store."""
    definition = CATALOG.get(code)
    if definition is None:
        if display is None:
            raise ValueError(f"display is required for observation code '{code}' (not in the catalog)")
        return ResolvedObservation(display=display, code_system=None, system_code=None)

    if value is None:
        raise ValueError(f"{code} requires value_numeric")
    if unit not in definition.units:
        allowed = ", ".join(definition.units)
        raise ValueError(f"unit for {code} must be one of: {allowed}")
    low, high = definition.units[unit]
    if not low <= value <= high:
        raise ValueError(f"{code} value {value:g} {unit} is outside the plausible range {low:g}-{high:g}")
    return ResolvedObservation(display=display or definition.display, code_system=LOINC, system_code=definition.loinc)
