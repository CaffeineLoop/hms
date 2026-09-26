"""Data access for patients. No business rules and no commits: the service owns the transaction."""

import re
import uuid
from datetime import date

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.patient import Patient, PatientStatus, patient_number_seq

_LIKE_ESCAPE = "\\"
_LIKE_SPECIAL = re.compile(r"([\\%_])")
MIN_PHONE_SEARCH_DIGITS = 3


def _contains(value: str) -> str:
    """ILIKE pattern matching `value` anywhere, with LIKE wildcards in the input escaped."""
    escaped = _LIKE_SPECIAL.sub(lambda match: _LIKE_ESCAPE + match.group(1), value)
    return f"%{escaped}%"


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def next_patient_number_value(self) -> int:
        """Draw the next value from patient_number_seq (values are never reused, gaps are possible)."""
        return self._session.execute(select(patient_number_seq.next_value())).scalar_one()

    def add(self, patient: Patient) -> Patient:
        self._session.add(patient)
        self._session.flush()
        return patient

    def get(self, patient_id: uuid.UUID, *, for_update: bool = False) -> Patient | None:
        statement = select(Patient).where(Patient.id == patient_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def search(
        self,
        *,
        search: str | None = None,
        status: PatientStatus | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Patient], int]:
        statement = self._filtered(select(Patient), search=search, status=status)
        total = self._session.execute(
            self._filtered(select(func.count()).select_from(Patient), search=search, status=status)
        ).scalar_one()
        items = self._session.execute(
            statement.order_by(Patient.created_at.desc(), Patient.patient_number.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(items), total

    def find_duplicates(
        self,
        *,
        first_name: str,
        last_name: str,
        date_of_birth: date,
        phone: str | None,
        email: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> list[Patient]:
        """Patients with the same name (case-insensitive) and date of birth who also share
        the phone number or email address. Uses ix_patients_lower_name_dob."""
        contact_matches = []
        if phone:
            contact_matches.append(Patient.phone == phone)
        if email:
            contact_matches.append(Patient.email == email)
        if not contact_matches:
            return []
        statement = select(Patient).where(
            func.lower(Patient.last_name) == last_name.lower(),
            func.lower(Patient.first_name) == first_name.lower(),
            Patient.date_of_birth == date_of_birth,
            or_(*contact_matches),
        )
        if exclude_id is not None:
            statement = statement.where(Patient.id != exclude_id)
        return list(self._session.execute(statement.order_by(Patient.patient_number)).scalars())

    @staticmethod
    def _filtered(statement: Select, *, search: str | None, status: PatientStatus | None) -> Select:
        if status is not None:
            statement = statement.where(Patient.status == status.value)
        if search:
            statement = statement.where(or_(*_search_conditions(search)))
        return statement


def _search_conditions(search: str) -> list[ColumnElement[bool]]:
    pattern = _contains(search)
    conditions = [
        Patient.patient_number.ilike(pattern, escape=_LIKE_ESCAPE),
        Patient.first_name.ilike(pattern, escape=_LIKE_ESCAPE),
        Patient.middle_name.ilike(pattern, escape=_LIKE_ESCAPE),
        Patient.last_name.ilike(pattern, escape=_LIKE_ESCAPE),
        func.concat_ws(" ", Patient.first_name, Patient.last_name).ilike(pattern, escape=_LIKE_ESCAPE),
        func.concat_ws(" ", Patient.first_name, Patient.middle_name, Patient.last_name).ilike(
            pattern, escape=_LIKE_ESCAPE
        ),
        Patient.email.ilike(pattern, escape=_LIKE_ESCAPE),
    ]
    # Phones are stored as digits (optionally '+'), so match on the digits the user typed.
    digits = re.sub(r"\D", "", search)
    if len(digits) >= MIN_PHONE_SEARCH_DIGITS:
        conditions.append(Patient.phone.contains(digits, autoescape=True))
    return conditions
