"""Clinical Records & Patient Timeline endpoints (Stage 2).

Records are created and listed under their patient; each record is also addressable
by its own id. There is no DELETE anywhere: clinical records are never removed.

    /api/patients/{patient_id}/encounters        POST, GET
    /api/patients/{patient_id}/observations      POST, GET
    /api/patients/{patient_id}/conditions        POST, GET
    /api/patients/{patient_id}/allergies         POST, GET
    /api/patients/{patient_id}/clinical-notes    POST, GET
    /api/patients/{patient_id}/timeline          GET

    /api/encounters/{id}                         GET
    /api/encounters/{id}/start|finish|cancel     POST   (controlled status changes)
    /api/observations/{id}                       GET
    /api/conditions/{id}                         GET, PATCH (status / resolution / notes)
    /api/allergies/{id}                          GET, PATCH (status / reaction / severity / notes)
    /api/clinical-notes/{id}                     GET
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.auth import requires
from app.api.authorship import bind_actor
from app.core.permissions import TIMELINE_EVENT_PERMISSIONS, P
from app.core.principal import Principal
from app.db.session import get_db
from app.schemas.clinical import (
    AllergyCreate,
    AllergyListParams,
    AllergyRead,
    AllergyUpdate,
    ClinicalNoteCreate,
    ClinicalNoteListParams,
    ClinicalNoteRead,
    ConditionCreate,
    ConditionListParams,
    ConditionRead,
    ConditionUpdate,
    EncounterCancel,
    EncounterCreate,
    EncounterFinish,
    EncounterListParams,
    EncounterRead,
    EncounterStart,
    ObservationCreate,
    ObservationListParams,
    ObservationRead,
)
from app.schemas.common import Page
from app.schemas.timeline import Timeline, TimelineParams
from app.services.clinical_record_service import (
    AllergyService,
    ClinicalNoteService,
    ConditionService,
    ObservationService,
)
from app.services.encounter_service import EncounterService
from app.services.timeline_service import TimelineService

router = APIRouter(prefix="/api", tags=["clinical records"])

_ERRORS = {
    404: {"description": "Patient or record not found"},
    409: {"description": "Invalid status transition, inactive patient, or conflicting record"},
    503: {"description": "Database unavailable"},
}
PATIENT = "/patients/{patient_id}"


def _service[S](cls: type[S]):
    def dependency(session: Session = Depends(get_db)) -> S:
        return cls(session)

    return Depends(dependency)


Encounters = Annotated[EncounterService, _service(EncounterService)]
Observations = Annotated[ObservationService, _service(ObservationService)]
Conditions = Annotated[ConditionService, _service(ConditionService)]
Allergies = Annotated[AllergyService, _service(AllergyService)]
Notes = Annotated[ClinicalNoteService, _service(ClinicalNoteService)]
TimelineDep = Annotated[TimelineService, _service(TimelineService)]


def _created(response: Response, path: str, record_id: uuid.UUID) -> None:
    response.headers["Location"] = f"{router.prefix}/{path}/{record_id}"


def _page(schema, result: tuple[list, int], params) -> dict:
    items, total = result
    return {
        "items": [schema.model_validate(item) for item in items],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


# --- encounters -----------------------------------------------------------------


@router.post(f"{PATIENT}/encounters", response_model=EncounterRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=["encounters"], dependencies=[requires(P.ENCOUNTER_CREATE)])
def create_encounter(patient_id: uuid.UUID, data: EncounterCreate, response: Response, service: Encounters):
    encounter = service.create(patient_id, data)
    _created(response, "encounters", encounter.id)
    return encounter


@router.get(f"{PATIENT}/encounters", response_model=Page[EncounterRead], responses=_ERRORS, tags=["encounters"], dependencies=[requires(P.ENCOUNTER_VIEW)])
def list_encounters(patient_id: uuid.UUID, params: Annotated[EncounterListParams, Query()], service: Encounters):
    return _page(EncounterRead, service.list_for_patient(patient_id, params), params)


@router.get("/encounters/{encounter_id}", response_model=EncounterRead, responses=_ERRORS, tags=["encounters"], dependencies=[requires(P.ENCOUNTER_VIEW)])
def get_encounter(encounter_id: uuid.UUID, service: Encounters):
    return service.get(encounter_id)


@router.post("/encounters/{encounter_id}/start", response_model=EncounterRead, responses=_ERRORS,
             tags=["encounters"], dependencies=[requires(P.ENCOUNTER_EDIT)])
def start_encounter(encounter_id: uuid.UUID, service: Encounters, data: EncounterStart | None = None):
    return service.start(encounter_id, data or EncounterStart())


@router.post("/encounters/{encounter_id}/finish", response_model=EncounterRead, responses=_ERRORS,
             tags=["encounters"], dependencies=[requires(P.ENCOUNTER_EDIT)])
def finish_encounter(encounter_id: uuid.UUID, service: Encounters, data: EncounterFinish | None = None):
    return service.finish(encounter_id, data or EncounterFinish())


@router.post("/encounters/{encounter_id}/cancel", response_model=EncounterRead, responses=_ERRORS,
             tags=["encounters"], dependencies=[requires(P.ENCOUNTER_EDIT)])
def cancel_encounter(encounter_id: uuid.UUID, data: EncounterCancel, service: Encounters):
    return service.cancel(encounter_id, data)


# --- observations ---------------------------------------------------------------


@router.post(f"{PATIENT}/observations", response_model=ObservationRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=["observations"], dependencies=[requires(P.OBSERVATION_CREATE)])
def create_observation(patient_id: uuid.UUID, data: ObservationCreate, response: Response, service: Observations):
    observation = service.create(patient_id, data)
    _created(response, "observations", observation.id)
    return observation


@router.get(f"{PATIENT}/observations", response_model=Page[ObservationRead], responses=_ERRORS,
            tags=["observations"], dependencies=[requires(P.OBSERVATION_VIEW)])
def list_observations(patient_id: uuid.UUID, params: Annotated[ObservationListParams, Query()],
                      service: Observations):
    return _page(ObservationRead, service.list_for_patient(patient_id, params), params)


@router.get("/observations/{observation_id}", response_model=ObservationRead, responses=_ERRORS,
            tags=["observations"], dependencies=[requires(P.OBSERVATION_VIEW)])
def get_observation(observation_id: uuid.UUID, service: Observations):
    return service.get(observation_id)


# --- conditions -----------------------------------------------------------------


@router.post(f"{PATIENT}/conditions", response_model=ConditionRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=["conditions"], dependencies=[requires(P.CONDITION_CREATE)])
def create_condition(patient_id: uuid.UUID, data: ConditionCreate, response: Response, service: Conditions):
    condition = service.create(patient_id, data)
    _created(response, "conditions", condition.id)
    return condition


@router.get(f"{PATIENT}/conditions", response_model=Page[ConditionRead], responses=_ERRORS, tags=["conditions"], dependencies=[requires(P.CONDITION_VIEW)])
def list_conditions(patient_id: uuid.UUID, params: Annotated[ConditionListParams, Query()], service: Conditions):
    return _page(ConditionRead, service.list_for_patient(patient_id, params), params)


@router.get("/conditions/{condition_id}", response_model=ConditionRead, responses=_ERRORS, tags=["conditions"], dependencies=[requires(P.CONDITION_VIEW)])
def get_condition(condition_id: uuid.UUID, service: Conditions):
    return service.get(condition_id)


@router.patch("/conditions/{condition_id}", response_model=ConditionRead, responses=_ERRORS, tags=["conditions"], dependencies=[requires(P.CONDITION_EDIT)])
def update_condition(condition_id: uuid.UUID, data: ConditionUpdate, service: Conditions):
    return service.update(condition_id, data)


# --- allergies ------------------------------------------------------------------


@router.post(f"{PATIENT}/allergies", response_model=AllergyRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=["allergies"], dependencies=[requires(P.ALLERGY_CREATE)])
def create_allergy(patient_id: uuid.UUID, data: AllergyCreate, response: Response, service: Allergies):
    allergy = service.create(patient_id, data)
    _created(response, "allergies", allergy.id)
    return allergy


@router.get(f"{PATIENT}/allergies", response_model=Page[AllergyRead], responses=_ERRORS, tags=["allergies"], dependencies=[requires(P.ALLERGY_VIEW)])
def list_allergies(patient_id: uuid.UUID, params: Annotated[AllergyListParams, Query()], service: Allergies):
    return _page(AllergyRead, service.list_for_patient(patient_id, params), params)


@router.get("/allergies/{allergy_id}", response_model=AllergyRead, responses=_ERRORS, tags=["allergies"], dependencies=[requires(P.ALLERGY_VIEW)])
def get_allergy(allergy_id: uuid.UUID, service: Allergies):
    return service.get(allergy_id)


@router.patch("/allergies/{allergy_id}", response_model=AllergyRead, responses=_ERRORS, tags=["allergies"], dependencies=[requires(P.ALLERGY_EDIT)])
def update_allergy(allergy_id: uuid.UUID, data: AllergyUpdate, service: Allergies):
    return service.update(allergy_id, data)


# --- clinical notes -------------------------------------------------------------


@router.post(f"{PATIENT}/clinical-notes", response_model=ClinicalNoteRead, status_code=status.HTTP_201_CREATED,
             responses=_ERRORS, tags=["clinical notes"])
def create_clinical_note(patient_id: uuid.UUID, data: ClinicalNoteCreate, response: Response, service: Notes, principal: Annotated[Principal, requires(P.CLINICAL_NOTE_CREATE)]):
    data = bind_actor(data, principal, "author_staff_id", "author_name")
    note = service.create(patient_id, data)
    _created(response, "clinical-notes", note.id)
    return note


@router.get(f"{PATIENT}/clinical-notes", response_model=Page[ClinicalNoteRead], responses=_ERRORS,
            tags=["clinical notes"], dependencies=[requires(P.CLINICAL_NOTE_VIEW)])
def list_clinical_notes(patient_id: uuid.UUID, params: Annotated[ClinicalNoteListParams, Query()], service: Notes):
    return _page(ClinicalNoteRead, service.list_for_patient(patient_id, params), params)


@router.get("/clinical-notes/{note_id}", response_model=ClinicalNoteRead, responses=_ERRORS,
            tags=["clinical notes"], dependencies=[requires(P.CLINICAL_NOTE_VIEW)])
def get_clinical_note(note_id: uuid.UUID, service: Notes):
    return service.get(note_id)


# --- timeline -------------------------------------------------------------------


@router.get(f"{PATIENT}/timeline", response_model=Timeline, responses=_ERRORS, tags=["timeline"])
def patient_timeline(patient_id: uuid.UUID, params: Annotated[TimelineParams, Query()], service: TimelineDep,
                     principal: Annotated[Principal, requires(P.TIMELINE_VIEW)]):
    visible = {event for event, needed in TIMELINE_EVENT_PERMISSIONS.items() if principal.has(needed)}
    events, total = service.timeline(patient_id, params, visible_types=visible)
    return Timeline(
        patient_id=patient_id, items=events, total=total,
        limit=params.limit, offset=params.offset, order=params.order,
    )
