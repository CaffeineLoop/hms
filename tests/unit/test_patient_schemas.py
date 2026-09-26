"""Patient input validation and normalization (no database)."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.core.clock import facility_today
from app.core.errors import BusinessValidationError
from app.models.patient import Sex, format_patient_number
from app.repositories.patient_repository import _contains
from app.schemas.patient import (
    PatientCreate,
    PatientDeactivate,
    PatientListParams,
    PatientUpdate,
)
from app.services.patient_service import _check_emergency_contact


def valid(**overrides):
    data = {
        "first_name": "Amina",
        "last_name": "Okafor",
        "date_of_birth": "1988-04-12",
        "sex": "FEMALE",
    }
    data.update(overrides)
    return data


def error_fields(exc: ValidationError) -> set[str]:
    return {str(error["loc"][0]) if error["loc"] else "" for error in exc.errors()}


# --- Patient ID -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "PAT-000001"), (42, "PAT-000042"), (999999, "PAT-999999"), (1000000, "PAT-1000000")],
)
def test_patient_number_format(value, expected):
    assert format_patient_number(value) == expected


def test_patient_number_rejects_non_positive():
    with pytest.raises(ValueError):
        format_patient_number(0)


# --- create -----------------------------------------------------------------


def test_minimal_valid_patient():
    patient = PatientCreate(**valid())
    assert patient.first_name == "Amina"
    assert patient.sex is Sex.FEMALE
    assert patient.middle_name is None and patient.phone is None and patient.email is None


def test_strings_are_stripped_and_blank_optionals_become_null():
    patient = PatientCreate(**valid(first_name="  Amina ", middle_name="   ", city=""))
    assert patient.first_name == "Amina"
    assert patient.middle_name is None
    assert patient.city is None


@pytest.mark.parametrize("field", ["first_name", "last_name", "date_of_birth", "sex"])
def test_required_fields(field):
    data = valid()
    del data[field]
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**data)
    assert field in error_fields(exc.value)


@pytest.mark.parametrize("field", ["first_name", "last_name"])
@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_invalid_names(field, value):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(**{field: value}))
    assert field in error_fields(exc.value)


def test_future_date_of_birth_rejected():
    tomorrow = (facility_today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError, match="cannot be in the future"):
        PatientCreate(**valid(date_of_birth=tomorrow))


def test_today_is_a_valid_date_of_birth():
    today = facility_today()
    assert PatientCreate(**valid(date_of_birth=today.isoformat())).date_of_birth == today


@pytest.mark.parametrize("value", ["1899-12-31", "not-a-date", "1990-02-30"])
def test_invalid_date_of_birth(value):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(date_of_birth=value))
    assert "date_of_birth" in error_fields(exc.value)


@pytest.mark.parametrize("value", ["F", "female", "", "X"])
def test_invalid_sex(value):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(sex=value))
    assert "sex" in error_fields(exc.value)


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("+254 712 345 678", "+254712345678"),
        ("(555) 123-4567", "5551234567"),
        ("0712.345.678", "0712345678"),
        ("00254 712 345 678", "+254712345678"),  # '00' international prefix == '+'
        ("0044 20 7946 0958", "+442079460958"),
        ("+1 (415) 555-0100", "+14155550100"),
    ],
)
def test_phone_is_normalized(raw, stored):
    assert PatientCreate(**valid(phone=raw)).phone == stored


@pytest.mark.parametrize(
    "value",
    ["12345", "phone", "+1234567890123456", "07-12-ab-34", "++254712345678", "+0712345678", "000712345678", "+123456"],
)
def test_invalid_phone(value):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(phone=value))
    assert "phone" in error_fields(exc.value)


def test_email_is_lowercased():
    assert PatientCreate(**valid(email=" Amina.O@Example.ORG ")).email == "amina.o@example.org"


@pytest.mark.parametrize("value", ["amina", "amina@", "@example.org", "a b@example.org", "a@example"])
def test_invalid_email(value):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(email=value))
    assert "email" in error_fields(exc.value)


@pytest.mark.parametrize("field", ["id", "patient_number", "status", "created_at", "diagnosis"])
def test_unknown_or_system_fields_rejected(field):
    with pytest.raises(ValidationError) as exc:
        PatientCreate(**valid(**{field: "x"}))
    assert field in error_fields(exc.value)


# --- update -----------------------------------------------------------------


def test_update_requires_at_least_one_field():
    with pytest.raises(ValidationError, match="at least one field"):
        PatientUpdate()


def test_update_tracks_only_supplied_fields():
    update = PatientUpdate(city="Nairobi", phone=None)
    assert update.model_dump(exclude_unset=True) == {"city": "Nairobi", "phone": None}


@pytest.mark.parametrize("field", ["first_name", "last_name", "date_of_birth", "sex"])
def test_update_cannot_clear_identity_fields(field):
    with pytest.raises(ValidationError, match=f"{field} cannot be null"):
        PatientUpdate(**{field: None})


@pytest.mark.parametrize("field", ["status", "patient_number", "id", "deactivated_at"])
def test_update_cannot_set_system_fields(field):
    with pytest.raises(ValidationError):
        PatientUpdate(**{field: "x"})


def test_update_rejects_future_date_of_birth():
    with pytest.raises(ValidationError, match="future"):
        PatientUpdate(date_of_birth=date.today() + timedelta(days=30))


# --- deactivate / list params ----------------------------------------------


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_deactivation_reason_required(reason):
    with pytest.raises(ValidationError):
        PatientDeactivate(reason=reason)


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "DELETED"}, {"q": "x" * 101}]
)
def test_invalid_list_params(params):
    with pytest.raises(ValidationError):
        PatientListParams(**params)


def test_list_param_defaults():
    params = PatientListParams()
    assert (params.q, params.status, params.limit, params.offset) == (None, None, 20, 0)


# --- helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "pattern"),
    [("ann", "%ann%"), ("50%", "%50\\%%"), ("a_b", "%a\\_b%"), ("c:\\x", "%c:\\\\x%")],
)
def test_search_pattern_escapes_like_wildcards(raw, pattern):
    assert _contains(raw) == pattern


@pytest.mark.parametrize(
    "values",
    [
        {"emergency_contact_name": "Ben"},
        {"emergency_contact_phone": "0712345678"},
        {"emergency_contact_relationship": "Brother"},
    ],
)
def test_incomplete_emergency_contact_rejected(values):
    with pytest.raises(BusinessValidationError):
        _check_emergency_contact(values)


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"emergency_contact_name": "Ben", "emergency_contact_phone": "0712345678"},
        {
            "emergency_contact_name": "Ben",
            "emergency_contact_phone": "0712345678",
            "emergency_contact_relationship": "Brother",
        },
    ],
)
def test_complete_or_absent_emergency_contact_accepted(values):
    _check_emergency_contact(values)
