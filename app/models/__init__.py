"""ORM model registry.

Every model module must be imported here so that its tables are registered on
`Base.metadata` before Alembic autogenerate inspects it (see alembic/env.py).
"""

from app.db.base import Base
from app.models.allergy import Allergy
from app.models.audit import AuditEvent
from app.models.auth import AuthSession, Permission, Role, RolePermission, User, UserRole
from app.models.clinical_note import ClinicalNote
from app.models.condition import Condition
from app.models.encounter import Encounter
from app.models.laboratory import LabOrder, LabResult, LabSample
from app.models.observation import Observation
from app.models.patient import Patient, PatientStatus, Sex
from app.models.prescription import Prescription, PrescriptionItem
from app.models.report import Report
from app.models.staff import Department, Staff
from app.models.workflow import Admission, AdmissionTransfer, Appointment, WorkflowTask

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Permission",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "Admission",
    "AdmissionTransfer",
    "Appointment",
    "Department",
    "Staff",
    "WorkflowTask",
    "Allergy",
    "Base",
    "ClinicalNote",
    "Condition",
    "Encounter",
    "LabOrder",
    "LabResult",
    "LabSample",
    "Observation",
    "Patient",
    "PatientStatus",
    "Prescription",
    "PrescriptionItem",
    "Report",
    "Sex",
]
