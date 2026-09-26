"""Patient timeline, derived on read from the underlying clinical records.

Each record type is registered once in TIMELINE_SOURCES with:
- the clinical timestamp that places it on the timeline,
- a rank used to order events that share the same instant,
- a short human-readable title and the response schema for its full record.

Later stages (procedures, ...) extend the timeline by appending a TimelineSource
here - no API or query changes needed.

Clinical timestamps used (and visibility rules):
    encounter     start_at
    observation   effective_at
    condition     onset_at when known, otherwise recorded_at
    allergy       recorded_at
    clinical_note authored_at
    lab_order     ordered_at      (all statuses; payload excludes results)
    lab_sample    collected_at
    lab_result    resulted_at     (only once the lab order is RELEASED)
    report        effective_at    (only RELEASED reports)
    prescription  prescribed_at   (not while DRAFT, i.e. only once issued)
    appointment   scheduled_start (all statuses; future bookings appear ahead of "now")
    admission     admitted_at, or requested_at until the patient is admitted
    admission_transfer  transferred_at
    workflow_task completed_at    (only COMPLETED tasks linked to the patient)
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.allergy import Allergy
from app.models.clinical_note import ClinicalNote
from app.models.condition import Condition
from app.models.encounter import Encounter
from app.models.laboratory import LabOrder, LabOrderStatus, LabResult, LabSample
from app.models.observation import Observation
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.report import Report, ReportStatus
from app.models.workflow import Admission, AdmissionTransfer, Appointment, TaskStatus, WorkflowTask
from app.repositories.timeline_repository import TimelineQuerySource, TimelineRepository
from app.schemas.clinical import (
    AllergyRead,
    ClinicalNoteRead,
    ConditionRead,
    EncounterRead,
    ObservationRead,
)
from app.schemas.diagnostics import (
    LabOrderSummaryRead,
    LabResultRead,
    LabSampleRead,
    PrescriptionRead,
    ReportRead,
)
from app.schemas.timeline import TimelineEvent, TimelineEventType, TimelineParams
from app.schemas.workflow import AdmissionSummaryRead, AdmissionTransferRead, AppointmentRead, TaskRead
from app.services.clinical_common import ClinicalContext


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _observation_title(o: Observation) -> str:
    value = f"{o.value_numeric:g} {o.unit or ''}".strip() if o.value_numeric is not None else o.value_text
    return f"{o.display}: {value}"


def _lab_result_title(r: LabResult) -> str:
    value = f"{r.value_numeric:g} {r.unit or ''}".strip() if r.value_numeric is not None else r.value_text
    flag = f" [{r.interpretation}]" if r.interpretation and r.interpretation != "NORMAL" else ""
    return f"{r.analyte_name}: {value}{flag}"


def _prescription_title(p: Prescription) -> str:
    medicines = ", ".join(item.medicine_name for item in p.items)
    return f"Prescription {p.prescription_number}: {medicines}"


@dataclass(frozen=True)
class TimelineSource:
    event_type: TimelineEventType
    query: TimelineQuerySource
    read_schema: type[BaseModel]
    title: Callable[[object], str]
    status: Callable[[object], str | None] = lambda record: getattr(record, "status", None)
    encounter_of: Callable[[object], uuid.UUID | None] = lambda record: getattr(record, "encounter_id", None)
    load_options: tuple = ()


TIMELINE_SOURCES: tuple[TimelineSource, ...] = (
    TimelineSource(
        TimelineEventType.ENCOUNTER,
        TimelineQuerySource("encounter", 0, Encounter, Encounter.start_at),
        EncounterRead,
        lambda e: f"{e.encounter_type.replace('_', ' ')} encounter: {e.reason}",
        encounter_of=lambda e: e.id,
    ),
    TimelineSource(
        TimelineEventType.OBSERVATION,
        TimelineQuerySource("observation", 1, Observation, Observation.effective_at),
        ObservationRead,
        _observation_title,
    ),
    TimelineSource(
        TimelineEventType.CONDITION,
        TimelineQuerySource("condition", 2, Condition, func.coalesce(Condition.onset_at, Condition.recorded_at)),
        ConditionRead,
        lambda c: f"Condition ({_label(c.status)}): {c.name}",
    ),
    TimelineSource(
        TimelineEventType.ALLERGY,
        TimelineQuerySource("allergy", 3, Allergy, Allergy.recorded_at),
        AllergyRead,
        lambda a: f"Allergy to {a.substance}" + (f" ({_label(a.severity)})" if a.severity else ""),
    ),
    TimelineSource(
        TimelineEventType.CLINICAL_NOTE,
        TimelineQuerySource("clinical_note", 4, ClinicalNote, ClinicalNote.authored_at),
        ClinicalNoteRead,
        lambda n: f"{_label(n.note_type)} note by {n.author_name}",
        status=lambda n: None,
    ),
    TimelineSource(
        TimelineEventType.LAB_ORDER,
        TimelineQuerySource("lab_order", 5, LabOrder, LabOrder.ordered_at),
        LabOrderSummaryRead,
        lambda o: f"Lab order {o.order_number}: {o.test_name}",
    ),
    TimelineSource(
        TimelineEventType.LAB_SAMPLE,
        TimelineQuerySource("lab_sample", 6, LabSample, LabSample.collected_at),
        LabSampleRead,
        lambda s: f"Sample {s.accession_number} collected ({_label(s.specimen_type)}) for {s.lab_order.order_number}",
        status=lambda s: None,
        encounter_of=lambda s: s.lab_order.encounter_id,
        load_options=(selectinload(LabSample.lab_order),),
    ),
    TimelineSource(
        TimelineEventType.LAB_RESULT,
        TimelineQuerySource(
            "lab_result", 7, LabResult, LabResult.resulted_at,
            where=LabResult.lab_order_id.in_(
                select(LabOrder.id).where(LabOrder.status == LabOrderStatus.RELEASED.value)
            ),
        ),
        LabResultRead,
        _lab_result_title,
        status=lambda r: None,
        encounter_of=lambda r: r.lab_order.encounter_id,
        load_options=(selectinload(LabResult.lab_order),),
    ),
    TimelineSource(
        TimelineEventType.REPORT,
        TimelineQuerySource(
            "report", 8, Report, Report.effective_at, where=Report.status == ReportStatus.RELEASED.value
        ),
        ReportRead,
        lambda r: f"{_label(r.report_type)} report: {r.title}",
    ),
    TimelineSource(
        TimelineEventType.PRESCRIPTION,
        TimelineQuerySource(
            "prescription", 9, Prescription, Prescription.prescribed_at,
            where=Prescription.status != PrescriptionStatus.DRAFT.value,
        ),
        PrescriptionRead,
        _prescription_title,
    ),
    TimelineSource(
        TimelineEventType.APPOINTMENT,
        TimelineQuerySource("appointment", 10, Appointment, Appointment.scheduled_start),
        AppointmentRead,
        lambda a: f"Appointment: {a.reason}",
    ),
    TimelineSource(
        TimelineEventType.ADMISSION,
        TimelineQuerySource("admission", 11, Admission, func.coalesce(Admission.admitted_at, Admission.requested_at)),
        AdmissionSummaryRead,
        lambda a: f"{_label(a.admission_type)} admission: {a.reason}",
    ),
    TimelineSource(
        TimelineEventType.ADMISSION_TRANSFER,
        TimelineQuerySource("admission_transfer", 12, AdmissionTransfer, AdmissionTransfer.transferred_at),
        AdmissionTransferRead,
        lambda t: f"Transferred: {t.reason}",
        status=lambda t: None,
    ),
    TimelineSource(
        TimelineEventType.WORKFLOW_TASK,
        TimelineQuerySource(
            "workflow_task", 13, WorkflowTask, WorkflowTask.completed_at,
            where=WorkflowTask.status == TaskStatus.COMPLETED.value,
        ),
        TaskRead,
        lambda t: f"Task completed: {t.title}",
    ),
)


class TimelineService:
    def __init__(self, session: Session, sources: tuple[TimelineSource, ...] = TIMELINE_SOURCES) -> None:
        self._repository = TimelineRepository(session)
        self._context = ClinicalContext(session)
        self._sources = {source.event_type: source for source in sources}

    def timeline(
        self, patient_id: uuid.UUID, params: TimelineParams, *, visible_types: set[str] | None = None
    ) -> tuple[list[TimelineEvent], int]:
        """`visible_types` (Stage 5): event types the caller may see; others are silently omitted."""
        self._context.patient(patient_id)
        wanted = [
            self._sources[t] for t in (params.types or self._sources)
            if t in self._sources and (visible_types is None or t.value in visible_types)
        ]
        rows, total = self._repository.page(
            patient_id,
            [source.query for source in wanted],
            occurred_from=params.occurred_from,
            occurred_to=params.occurred_to,
            order=params.order,
            limit=params.limit,
            offset=params.offset,
        )

        records: dict[tuple[str, uuid.UUID], object] = {}
        for source in wanted:
            ids = [row.record_id for row in rows if row.event_type == source.event_type.value]
            for record_id, record in self._repository.load(source.query.model, ids, source.load_options).items():
                records[(source.event_type.value, record_id)] = record

        events = []
        for row in rows:
            source = self._sources[TimelineEventType(row.event_type)]
            record = records[(row.event_type, row.record_id)]
            events.append(
                TimelineEvent(
                    event_type=source.event_type,
                    occurred_at=row.occurred_at,
                    record_id=row.record_id,
                    encounter_id=source.encounter_of(record),
                    title=source.title(record),
                    status=source.status(record),
                    data=source.read_schema.model_validate(record).model_dump(mode="json"),
                )
            )
        return events, total
