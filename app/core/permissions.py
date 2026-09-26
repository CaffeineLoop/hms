"""The permission catalog and the default role templates (Stage 5).

Permission CODES live in code because the backend checks them; which ROLES hold which
permissions lives in the database and is managed through the API (dynamic RBAC). The
migration that introduced RBAC seeded the `permissions` table from this catalog and the
default roles from DEFAULT_ROLES; a test asserts the catalog and the database agree.

Scopes (role_permissions.scope):
    ALL  - every matching record (default)
    OWN  - only records tied to the user's own staff member; currently honoured for
           workflow tasks (tasks assigned to the user). Other resources treat OWN as "no
           record-level access" until they gain an owner notion.
Reserved for later stages (not yet valid values): DEPARTMENT, ASSIGNED.
"""

from enum import StrEnum


class Scope(StrEnum):
    ALL = "ALL"
    OWN = "OWN"


SCOPE_RANK = {Scope.OWN: 1, Scope.ALL: 2}


class P(StrEnum):
    """Permission codes. Values are what the API and database use."""

    PATIENT_VIEW = "patient.view"
    PATIENT_CREATE = "patient.create"
    PATIENT_EDIT = "patient.edit"

    ENCOUNTER_VIEW = "encounter.view"
    ENCOUNTER_CREATE = "encounter.create"
    ENCOUNTER_EDIT = "encounter.edit"

    OBSERVATION_VIEW = "observation.view"
    OBSERVATION_CREATE = "observation.create"
    CONDITION_VIEW = "condition.view"
    CONDITION_CREATE = "condition.create"
    CONDITION_EDIT = "condition.edit"
    ALLERGY_VIEW = "allergy.view"
    ALLERGY_CREATE = "allergy.create"
    ALLERGY_EDIT = "allergy.edit"
    CLINICAL_NOTE_VIEW = "clinical_note.view"
    CLINICAL_NOTE_CREATE = "clinical_note.create"
    TIMELINE_VIEW = "timeline.view"

    LAB_VIEW = "lab.view"
    LAB_ORDER = "lab.order"
    LAB_COLLECT = "lab.collect"
    LAB_PROCESS = "lab.process"
    LAB_VERIFY = "lab.verify"

    REPORT_VIEW = "report.view"
    REPORT_CREATE = "report.create"
    REPORT_VERIFY = "report.verify"

    PRESCRIPTION_VIEW = "prescription.view"
    PRESCRIPTION_CREATE = "prescription.create"
    PRESCRIPTION_EDIT = "prescription.edit"

    STAFF_VIEW = "staff.view"
    STAFF_MANAGE = "staff.manage"

    APPOINTMENT_VIEW = "appointment.view"
    APPOINTMENT_MANAGE = "appointment.manage"
    ADMISSION_VIEW = "admission.view"
    ADMISSION_MANAGE = "admission.manage"
    WORKFLOW_VIEW = "workflow.view"
    WORKFLOW_MANAGE = "workflow.manage"

    USER_VIEW = "user.view"
    USER_MANAGE = "user.manage"
    ROLE_MANAGE = "role.manage"
    PERMISSION_MANAGE = "permission.manage"

    AUDIT_VIEW = "audit.view"  # Stage 6

    # Reserved for later stages; seeded so roles can be prepared, not yet checked anywhere.
    AI_ANALYSIS = "ai.analysis"
    AI_REVIEW = "ai.review"


DESCRIPTIONS: dict[P, str] = {
    P.PATIENT_VIEW: "View and search patients",
    P.PATIENT_CREATE: "Register patients",
    P.PATIENT_EDIT: "Edit patient details, deactivate/reactivate patients",
    P.ENCOUNTER_VIEW: "View encounters",
    P.ENCOUNTER_CREATE: "Open or document encounters",
    P.ENCOUNTER_EDIT: "Start, finish or cancel encounters",
    P.OBSERVATION_VIEW: "View observations and vital signs",
    P.OBSERVATION_CREATE: "Record observations and vital signs",
    P.CONDITION_VIEW: "View conditions",
    P.CONDITION_CREATE: "Document conditions",
    P.CONDITION_EDIT: "Change condition status",
    P.ALLERGY_VIEW: "View allergies",
    P.ALLERGY_CREATE: "Document allergies",
    P.ALLERGY_EDIT: "Update allergies",
    P.CLINICAL_NOTE_VIEW: "Read clinical notes",
    P.CLINICAL_NOTE_CREATE: "Write clinical notes",
    P.TIMELINE_VIEW: "View the patient timeline (events limited to the other view permissions held)",
    P.LAB_VIEW: "View lab orders, samples and results",
    P.LAB_ORDER: "Order and cancel lab tests",
    P.LAB_COLLECT: "Record sample collection",
    P.LAB_PROCESS: "Process samples, enter and correct results",
    P.LAB_VERIFY: "Verify and release lab results",
    P.REPORT_VIEW: "View reports",
    P.REPORT_CREATE: "Create, edit and cancel draft reports",
    P.REPORT_VERIFY: "Verify and release reports",
    P.PRESCRIPTION_VIEW: "View prescriptions",
    P.PRESCRIPTION_CREATE: "Write, edit and issue prescriptions",
    P.PRESCRIPTION_EDIT: "Hold, resume, complete or cancel prescriptions",
    P.STAFF_VIEW: "View departments and staff",
    P.STAFF_MANAGE: "Manage departments and staff",
    P.APPOINTMENT_VIEW: "View appointments",
    P.APPOINTMENT_MANAGE: "Book and progress appointments",
    P.ADMISSION_VIEW: "View admissions",
    P.ADMISSION_MANAGE: "Request, approve, admit, transfer and discharge",
    P.WORKFLOW_VIEW: "View workflow tasks",
    P.WORKFLOW_MANAGE: "Create, assign and progress workflow tasks",
    P.USER_VIEW: "View user accounts",
    P.USER_MANAGE: "Create/deactivate user accounts, reset passwords, assign roles",
    P.ROLE_MANAGE: "Create, edit and deactivate roles",
    P.PERMISSION_MANAGE: "Grant and revoke role permissions",
    P.AUDIT_VIEW: "View the audit trail",
    P.AI_ANALYSIS: "Run AI analysis (reserved for a later stage)",
    P.AI_REVIEW: "Review AI output (reserved for a later stage)",
}

# Timeline event type -> permission needed to see that type of event.
TIMELINE_EVENT_PERMISSIONS: dict[str, P] = {
    "encounter": P.ENCOUNTER_VIEW,
    "observation": P.OBSERVATION_VIEW,
    "condition": P.CONDITION_VIEW,
    "allergy": P.ALLERGY_VIEW,
    "clinical_note": P.CLINICAL_NOTE_VIEW,
    "lab_order": P.LAB_VIEW,
    "lab_sample": P.LAB_VIEW,
    "lab_result": P.LAB_VIEW,
    "report": P.REPORT_VIEW,
    "prescription": P.PRESCRIPTION_VIEW,
    "appointment": P.APPOINTMENT_VIEW,
    "admission": P.ADMISSION_VIEW,
    "admission_transfer": P.ADMISSION_VIEW,
    "workflow_task": P.WORKFLOW_VIEW,
}

SUPER_ADMIN = "SUPER_ADMIN"

_CLINICAL_READ = [
    P.PATIENT_VIEW, P.ENCOUNTER_VIEW, P.OBSERVATION_VIEW, P.CONDITION_VIEW, P.ALLERGY_VIEW,
    P.CLINICAL_NOTE_VIEW, P.TIMELINE_VIEW, P.LAB_VIEW, P.REPORT_VIEW, P.PRESCRIPTION_VIEW,
    P.APPOINTMENT_VIEW, P.ADMISSION_VIEW, P.STAFF_VIEW,
]

# Default roles seeded by the RBAC migration: {role: (description, {permission: scope})}.
# SUPER_ADMIN is a system role that implicitly holds every permission (present and future).
DEFAULT_ROLES: dict[str, tuple[str, dict[P, Scope]]] = {
    SUPER_ADMIN: ("System administrator: every permission (system role, cannot be edited)", {}),
    "DOCTOR": ("Clinician: full clinical documentation, orders and prescriptions", {
        **{p: Scope.ALL for p in _CLINICAL_READ},
        **{p: Scope.ALL for p in (
            P.PATIENT_CREATE, P.PATIENT_EDIT, P.ENCOUNTER_CREATE, P.ENCOUNTER_EDIT, P.OBSERVATION_CREATE,
            P.CONDITION_CREATE, P.CONDITION_EDIT, P.ALLERGY_CREATE, P.ALLERGY_EDIT, P.CLINICAL_NOTE_CREATE,
            P.LAB_ORDER, P.REPORT_CREATE, P.REPORT_VERIFY, P.PRESCRIPTION_CREATE, P.PRESCRIPTION_EDIT,
            P.APPOINTMENT_MANAGE, P.ADMISSION_MANAGE, P.WORKFLOW_VIEW, P.WORKFLOW_MANAGE,
        )},
    }),
    "NURSE": ("Nursing: observations, notes, sample collection, own tasks", {
        **{p: Scope.ALL for p in _CLINICAL_READ},
        **{p: Scope.ALL for p in (
            P.OBSERVATION_CREATE, P.ALLERGY_CREATE, P.CLINICAL_NOTE_CREATE, P.LAB_COLLECT,
            P.APPOINTMENT_MANAGE, P.ADMISSION_MANAGE,
        )},
        P.WORKFLOW_VIEW: Scope.OWN,
        P.WORKFLOW_MANAGE: Scope.OWN,
    }),
    "RECEPTIONIST": ("Front desk: registration and appointments", {
        p: Scope.ALL for p in (
            P.PATIENT_VIEW, P.PATIENT_CREATE, P.PATIENT_EDIT, P.APPOINTMENT_VIEW, P.APPOINTMENT_MANAGE,
            P.ADMISSION_VIEW, P.STAFF_VIEW,
        )
    }),
    "LAB_TECHNICIAN": ("Laboratory: samples, processing, result entry, lab reports", {
        p: Scope.ALL for p in (
            P.PATIENT_VIEW, P.LAB_VIEW, P.LAB_COLLECT, P.LAB_PROCESS, P.REPORT_VIEW, P.REPORT_CREATE, P.STAFF_VIEW,
        )
    }),
    "PHARMACIST": ("Pharmacy: review and progress prescriptions", {
        p: Scope.ALL for p in (
            P.PATIENT_VIEW, P.ALLERGY_VIEW, P.PRESCRIPTION_VIEW, P.PRESCRIPTION_EDIT, P.STAFF_VIEW,
        )
    }),
}
