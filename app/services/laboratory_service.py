"""Laboratory workflow. See app/models/laboratory.py for the lifecycle diagram.

Rules (in addition to clinical_common's patient/encounter/birth rules):
- a new order needs an ACTIVE patient and an IN_PROGRESS/FINISHED encounter of that patient;
- samples may be collected while ORDERED / SAMPLE_COLLECTED / PROCESSING; the first
  sample moves ORDERED -> SAMPLE_COLLECTED; collection cannot precede the order;
- results may be entered/corrected only while PROCESSING / RESULT_ENTERED; the first
  submission moves PROCESSING -> RESULT_ENTERED; one result per analyte per order;
- VERIFIED requires at least one result and locks the results; RELEASED makes them
  visible on the patient timeline;
- every other status change goes through LAB_ORDER_TRANSITIONS (409 otherwise).
Workflow steps continue even if the patient is later deactivated: an order in flight
must still be completed or cancelled.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.clock import now_not_before as not_before
from app.core.clock import utc_now
from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.clinical_base import format_identifier
from app.models.laboratory import (
    LAB_ORDER_PREFIX,
    LAB_ORDER_TRANSITIONS,
    LAB_SAMPLE_PREFIX,
    RESULT_ENTRY_STATUSES,
    SAMPLE_COLLECTION_STATUSES,
    LabOrder,
    LabOrderStatus,
    LabResult,
    LabSample,
    lab_order_number_seq,
    lab_sample_accession_seq,
)
from app.repositories.clinical_repository import (
    LabOrderRepository,
    LabResultRepository,
    LabSampleRepository,
    SequenceRepository,
)
from app.schemas.diagnostics import (
    CancelRequest,
    LabOrderCreate,
    LabOrderListParams,
    LabResultsSubmit,
    LabResultUpdate,
    LabSampleCreate,
    LabVerify,
    check_result_values,
    derive_interpretation,
)
from app.services.clinical_common import (
    ClinicalContext,
    check_not_before_birth,
    check_not_before_encounter,
    ensure_transition,
)
from app.services.staff_directory import StaffDirectory

_RANGE_FIELDS = {"value_numeric", "reference_low", "reference_high"}


class LabOrderService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = LabOrderRepository(session)
        self._samples = LabSampleRepository(session)
        self._results = LabResultRepository(session)
        self._sequences = SequenceRepository(session)
        self._context = ClinicalContext(session)
        self._directory = StaffDirectory(session)

    # --- queries ------------------------------------------------------------------

    def get(self, order_id: uuid.UUID) -> LabOrder:
        return self._get_order(order_id)

    def get_sample(self, sample_id: uuid.UUID) -> LabSample:
        sample = self._samples.get(sample_id)
        if sample is None:
            raise NotFoundError(f"Lab sample {sample_id} not found.")
        return sample

    def get_result(self, result_id: uuid.UUID) -> LabResult:
        return self._get_result(result_id)

    def list_for_patient(self, patient_id: uuid.UUID, params: LabOrderListParams) -> tuple[list[LabOrder], int]:
        self._context.patient(patient_id)
        return self._orders.list_for_patient(
            patient_id,
            filters={"status": params.status, "encounter_id": params.encounter_id, "test_code": params.test_code},
            limit=params.limit,
            offset=params.offset,
        )

    # --- commands -----------------------------------------------------------------

    def create(self, patient_id: uuid.UUID, data: LabOrderCreate) -> LabOrder:
        patient = self._context.patient_for_recording(patient_id)
        encounter = self._context.encounter_for_recording(patient, data.encounter_id)
        values = data.model_dump()
        values["ordered_at"] = data.ordered_at or utc_now()
        values["ordered_by_staff_id"], values["ordered_by"] = self._directory.person(
            data.ordered_by_staff_id, data.ordered_by, "ordered_by_staff_id"
        )
        check_not_before_birth(patient, values["ordered_at"], "ordered_at")
        check_not_before_encounter(encounter, values["ordered_at"], "ordered_at")
        order = LabOrder(
            patient_id=patient.id,
            order_number=format_identifier(LAB_ORDER_PREFIX, self._sequences.next_value(lab_order_number_seq)),
            status=LabOrderStatus.ORDERED.value,
            **values,
        )
        self._orders.add(order)
        return self._save(order)

    def collect_sample(self, order_id: uuid.UUID, data: LabSampleCreate) -> LabSample:
        order = self._get_order(order_id, for_update=True)
        if order.status not in SAMPLE_COLLECTION_STATUSES:
            raise ConflictError(f"Lab order {order.order_number} is {order.status}; samples cannot be collected.")
        collected_by_staff_id, collected_by = self._directory.person(
            data.collected_by_staff_id, data.collected_by, "collected_by_staff_id"
        )
        collected_at = data.collected_at or not_before(order.ordered_at)
        if collected_at < order.ordered_at:
            raise BusinessValidationError("collected_at cannot be before the order's ordered_at", field="collected_at")
        sample = LabSample(
            patient_id=order.patient_id,
            lab_order_id=order.id,
            accession_number=format_identifier(
                LAB_SAMPLE_PREFIX, self._sequences.next_value(lab_sample_accession_seq)
            ),
            specimen_type=data.specimen_type.value,
            collected_at=collected_at,
            collected_by=collected_by,
            collected_by_staff_id=collected_by_staff_id,
            notes=data.notes,
        )
        self._samples.add(sample)
        if order.status == LabOrderStatus.ORDERED:
            order.status = LabOrderStatus.SAMPLE_COLLECTED.value
        self._session.commit()
        self._session.refresh(sample)
        return sample

    def start_processing(self, order_id: uuid.UUID) -> LabOrder:
        order = self._get_order(order_id, for_update=True)
        self._transition(order, LabOrderStatus.PROCESSING)
        order.status = LabOrderStatus.PROCESSING.value
        order.processing_started_at = not_before(order.ordered_at)
        return self._save(order)

    def submit_results(self, order_id: uuid.UUID, data: LabResultsSubmit) -> LabOrder:
        order = self._get_order(order_id, for_update=True)
        if order.status not in RESULT_ENTRY_STATUSES:
            raise ConflictError(
                f"Lab order {order.order_number} is {order.status}; results can only be entered while "
                "PROCESSING or RESULT_ENTERED."
            )
        existing = {result.analyte_code for result in order.results}
        repeated = sorted(existing & {r.analyte_code for r in data.results})
        if repeated:
            raise ConflictError(
                f"Results already exist for {', '.join(repeated)}; correct them with PATCH /api/lab-results/{{id}}."
            )
        entered_by_staff_id, entered_by = self._directory.person(
            data.entered_by_staff_id, data.entered_by, "entered_by_staff_id"
        )
        latest_sample = max((s.collected_at for s in order.samples), default=order.ordered_at)
        for index, item in enumerate(data.results):
            resulted_at = item.resulted_at or not_before(latest_sample)
            if resulted_at < latest_sample:
                raise BusinessValidationError(
                    f"results[{index}].resulted_at cannot be before the sample collection time",
                    field="results",
                )
            self._results.add(
                LabResult(
                    patient_id=order.patient_id,
                    lab_order_id=order.id,
                    entered_by=entered_by,
                    entered_by_staff_id=entered_by_staff_id,
                    **(item.model_dump() | {"resulted_at": resulted_at}),
                )
            )
        if order.status == LabOrderStatus.PROCESSING:
            order.status = LabOrderStatus.RESULT_ENTERED.value
            order.results_entered_at = not_before(order.processing_started_at)
        return self._save(order)

    def update_result(self, result_id: uuid.UUID, data: LabResultUpdate) -> LabResult:
        result = self._get_result(result_id, for_update=True)
        order = self._get_order(result.lab_order_id, for_update=True)
        if order.status not in RESULT_ENTRY_STATUSES:
            raise ConflictError(f"Lab order {order.order_number} is {order.status}; its results are locked.")
        changes = data.model_dump(exclude_unset=True)
        changes["entered_by_staff_id"], changes["entered_by"] = self._directory.person(
            data.entered_by_staff_id, data.entered_by, "entered_by_staff_id"
        )
        people = {"entered_by", "entered_by_staff_id"}
        merged = {field: getattr(result, field) for field in LabResultUpdate.model_fields if field not in people}
        merged |= {k: v for k, v in changes.items() if k not in people}
        try:
            check_result_values(merged)
        except ValueError as exc:
            raise BusinessValidationError(str(exc)) from None
        if "interpretation" not in changes and _RANGE_FIELDS & changes.keys():
            changes["interpretation"] = derive_interpretation(
                merged["value_numeric"], merged["reference_low"], merged["reference_high"]
            )
        for field, value in changes.items():
            setattr(result, field, value)
        self._session.commit()
        self._session.refresh(result)
        return result

    def verify(self, order_id: uuid.UUID, data: LabVerify) -> LabOrder:
        order = self._get_order(order_id, for_update=True)
        self._transition(order, LabOrderStatus.VERIFIED)
        if not order.results:
            raise ConflictError(f"Lab order {order.order_number} has no results to verify.")
        order.status = LabOrderStatus.VERIFIED.value
        order.verified_by_staff_id, order.verified_by = self._directory.person(
            data.verified_by_staff_id, data.verified_by, "verified_by_staff_id"
        )
        order.verified_at = not_before(order.results_entered_at or order.ordered_at)
        return self._save(order)

    def release(self, order_id: uuid.UUID) -> LabOrder:
        order = self._get_order(order_id, for_update=True)
        self._transition(order, LabOrderStatus.RELEASED)
        order.status = LabOrderStatus.RELEASED.value
        order.released_at = not_before(order.verified_at)
        return self._save(order)

    def cancel(self, order_id: uuid.UUID, data: CancelRequest) -> LabOrder:
        order = self._get_order(order_id, for_update=True)
        self._transition(order, LabOrderStatus.CANCELLED)
        order.status = LabOrderStatus.CANCELLED.value
        order.cancelled_at = utc_now()
        order.cancellation_reason = data.reason
        return self._save(order)

    # --- helpers ------------------------------------------------------------------

    def _transition(self, order: LabOrder, target: LabOrderStatus) -> None:
        ensure_transition(f"Lab order {order.order_number}", order.status, target, LAB_ORDER_TRANSITIONS)

    def _save(self, order: LabOrder) -> LabOrder:
        self._session.commit()
        self._session.refresh(order)  # also reloads samples/results
        return order

    def _get_order(self, order_id: uuid.UUID, *, for_update: bool = False) -> LabOrder:
        order = self._orders.get(order_id, for_update=for_update)
        if order is None:
            raise NotFoundError(f"Lab order {order_id} not found.")
        return order

    def _get_result(self, result_id: uuid.UUID, *, for_update: bool = False) -> LabResult:
        result = self._results.get(result_id, for_update=for_update)
        if result is None:
            raise NotFoundError(f"Lab result {result_id} not found.")
        return result
