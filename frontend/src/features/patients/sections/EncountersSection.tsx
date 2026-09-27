/** Encounters list (GET /patients/{id}/encounters: status, encounter_type, paging) and encounter detail. */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../../api/client'
import { clinicalApi } from '../../../api/endpoints'
import type { ClinicalNote, Encounter } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import type { Column } from '../../../components/ui'
import {
  Alert, Card, DataTable, DescriptionList, EmptyState, ErrorState, Field, LinkButton, LoadingState, Pagination,
  ProvenanceTag, Select, StatusBadge,
} from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import { bloodPressureValue, observationValue, pairBloodPressure } from '../../../lib/clinical'
import { formatDateTime, humanize } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { NoteCard, SectionHead, StaffName } from '../shared'
import { EncounterActions, SavedNotice } from '../writes/ClinicalForms'

const PAGE_SIZE = 20

function duration(start: string, end: string | null): string | null {
  if (!end) return null
  const minutes = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000)
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ${minutes % 60} min`
  return `${Math.floor(hours / 24)} days`
}

export function EncountersSection() {
  const { patient } = usePatientRecord()
  const { hasAllScope } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => clinicalApi.encounters(patient.id,
    { status: status || undefined, encounter_type: type || undefined, limit: PAGE_SIZE, offset }, s), [patient.id, status, type, offset])

  const columns: Column<Encounter>[] = [
    { key: 'start', header: 'Started', numeric: true, width: 180, render: (e) => <span className="cell-strong">{formatDateTime(e.start_at)}</span> },
    { key: 'type', header: 'Type', render: (e) => humanize(e.encounter_type) },
    { key: 'reason', header: 'Reason', render: (e) => <span className="cell-stack"><span>{e.reason}</span>
      {e.cancellation_reason ? <span className="cell-sub">Cancelled: {e.cancellation_reason}</span> : null}</span> },
    { key: 'end', header: 'Ended', priority: 'secondary', numeric: true,
      render: (e) => (e.end_at ? formatDateTime(e.end_at) : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'Status', render: (e) => <StatusBadge status={e.status} size="sm" /> },
  ]

  return (
    <>
      <SavedNotice />
      <SectionHead title="Encounters" meta={result.data ? <span>{result.data.total} recorded</span> : null}>
        {hasAllScope('encounter.create') ? <LinkButton to="new" variant="primary" icon="plus">New encounter</LinkButton> : null}
        <Field label="Status">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
            <option value="">All statuses</option>
            {['PLANNED', 'IN_PROGRESS', 'FINISHED', 'CANCELLED'].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
        </Field>
        <Field label="Type">
          <Select value={type} onChange={(e) => { setType(e.target.value); setOffset(0) }}>
            <option value="">All types</option>
            {['OPD', 'EMERGENCY', 'INPATIENT', 'FOLLOW_UP'].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
        </Field>
      </SectionHead>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Encounters" columns={columns} rows={result.data?.items} rowKey={(e) => e.id}
              loading={result.loading && !result.data} onRowClick={(e) => navigate(e.id)}
              rowLabel={(e) => `Open ${humanize(e.encounter_type)} encounter of ${formatDateTime(e.start_at)}`}
              empty={<EmptyState icon="clinical" title={status || type ? 'No encounters match these filters' : 'No encounters recorded'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="encounters" /> : null}
          </>
        )}
      </Card>
    </>
  )
}

export function EncounterDetailPage() {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  const { encounterId = '' } = useParams()
  const encounter = useQuery((s) => clinicalApi.encounter(patient.id, encounterId, s), [patient.id, encounterId])
  const back = <LinkButton to={`/patients/${patient.id}/encounters`} variant="ghost" size="sm" icon="chevronLeft">All encounters</LinkButton>

  // The patient-scoped endpoint returns 404 unless the encounter belongs to this patient (enforced by the backend).
  if (encounter.error instanceof ApiError && encounter.error.status === 404) {
    return <Alert tone="danger" title="Encounter not found for this patient">
      No encounter with this reference is recorded for this patient. {back}</Alert>
  }
  if (encounter.error) return <Card>{back}<ErrorState error={encounter.error} onRetry={encounter.reload} /></Card>
  if (!encounter.data) return <LoadingState label="Loading encounter…" />
  const e = encounter.data

  return (
    <div className="stack" >
      <SavedNotice />
      <div className="cluster cluster--between">{back}<EncounterActions encounter={e} onChanged={encounter.reload} /></div>
      <Card title={<span className="enc-head">{humanize(e.encounter_type)} encounter <StatusBadge status={e.status} size="sm" /></span>}
        description={e.reason} actions={<ProvenanceTag kind="record" />}>
        <DescriptionList columns={3} items={[
          { label: 'Started', value: formatDateTime(e.start_at) },
          { label: 'Ended', value: e.end_at ? formatDateTime(e.end_at) : null },
          { label: 'Duration', value: duration(e.start_at, e.end_at) },
          { label: 'Attending clinician', value: <StaffName staffId={e.attending_staff_id} /> },
          { label: 'Type', value: humanize(e.encounter_type) },
          { label: 'Status', value: humanize(e.status) },
          { label: 'Reason for visit', value: e.reason, wide: true },
          { label: 'Summary', value: e.summary ? <span className="enc-summary">{e.summary}</span> : null, wide: true },
          ...(e.cancellation_reason ? [{ label: 'Cancellation reason', value: e.cancellation_reason, wide: true }] : []),
        ]} />
      </Card>
      {canReadClinical('observation.view') ? <EncounterObservations patientId={patient.id} encounterId={e.id} /> : null}
      {canReadClinical('clinical_note.view') ? <EncounterNotes patientId={patient.id} encounterId={e.id} /> : null}
    </div>
  )
}

function EncounterObservations({ patientId, encounterId }: { patientId: string; encounterId: string }) {
  const result = useQuery((s) => clinicalApi.observations(patientId, { encounter_id: encounterId, limit: 100 }, s), [patientId, encounterId])
  const rows = result.data ? pairBloodPressure(result.data.items) : undefined
  return (
    <Card title="Observations in this encounter" padding="none"
      description={result.data && result.data.total > 100 ? `Showing the latest 100 of ${result.data.total}` : undefined}>
      {result.error ? <ErrorState compact error={result.error} /> : (
        <DataTable caption="Observations in this encounter" rows={rows} rowKey={(r) => r.key} loading={result.loading && !result.data} density="compact"
          empty={<EmptyState compact icon="pulse" title="No observations recorded in this encounter" />}
          columns={[
            { key: 'when', header: 'Recorded', numeric: true, width: 180, render: (r) => formatDateTime(r.kind === 'bp' ? r.systolic.effective_at : r.observation.effective_at) },
            { key: 'what', header: 'Measurement', render: (r) => (r.kind === 'bp' ? 'Blood pressure' : r.observation.display) },
            { key: 'value', header: 'Value', align: 'right', numeric: true,
              render: (r) => <span className="value-strong">{r.kind === 'bp' ? bloodPressureValue(r.systolic, r.diastolic) : observationValue(r.observation)}</span> },
          ]} />
      )}
    </Card>
  )
}

function EncounterNotes({ patientId, encounterId }: { patientId: string; encounterId: string }) {
  const result = useQuery((s) => clinicalApi.notes(patientId, { encounter_id: encounterId, limit: 50 }, s), [patientId, encounterId])
  return (
    <Card title="Clinical notes in this encounter" padding="none">
      {result.error ? <ErrorState compact error={result.error} />
        : result.loading && !result.data ? <LoadingState rows={2} />
          : !result.data || result.data.items.length === 0 ? <EmptyState compact icon="edit" title="No notes recorded in this encounter" />
            : <div className="notes-list notes-list--inset">
              {result.data.items.map((n: ClinicalNote) => <NoteCard key={n.id} note={n} />)}
            </div>}
    </Card>
  )
}
