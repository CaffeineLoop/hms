/** Patient overview: demographics as recorded + permission-gated clinical snapshots (links into each section). */
import { useLocation } from 'react-router-dom'
import { clinicalApi } from '../../../api/endpoints'
import { useAuth } from '../../../auth/useAuth'
import {
  Alert, Card, DescriptionList, EmptyState, ErrorState, LinkButton, LoadingState, ProvenanceTag, StatusBadge,
} from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import { bloodPressureValue, latestVitals, observationValue, VITAL_ORDER } from '../../../lib/clinical'
import { formatDate, formatDateTime, formatRelative, formatShortDateTime, humanize, sexLabel } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'

export function OverviewSection() {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  const base = `/patients/${patient.id}`

  const address = [patient.address_line1, patient.address_line2, patient.city, patient.state_province,
    patient.postal_code, patient.country].filter(Boolean).join(', ')

  return (
    <div className="overview-grid">
      {notice ? <div className="span-12"><Alert tone="success">{notice}</Alert></div> : null}

      <Card className="span-7" title="Demographics" description="As recorded at registration and later updates"
        actions={<ProvenanceTag kind="record" />}>
        <DescriptionList columns={2} items={[
          { label: 'First name', value: patient.first_name },
          { label: 'Middle name', value: patient.middle_name },
          { label: 'Last name', value: patient.last_name },
          { label: 'Date of birth', value: formatDate(`${patient.date_of_birth}T00:00:00`) },
          { label: 'Sex', value: sexLabel(patient.sex) },
          { label: 'Patient ID', value: <span className="mono">{patient.patient_number}</span> },
          { label: 'Phone', value: patient.phone },
          { label: 'Email', value: patient.email },
          { label: 'Address', value: address, wide: true },
        ]} />
      </Card>

      <div className="span-5 overview-side">
        <Card title="Record status" actions={<ProvenanceTag kind="system" />}>
          <DescriptionList columns={2} items={[
            { label: 'Status', value: <StatusBadge status={patient.status} size="sm" /> },
            { label: 'Registered', value: formatDateTime(patient.created_at) },
            { label: 'Last updated', value: formatRelative(patient.updated_at) },
            ...(patient.status === 'INACTIVE' ? [
              { label: 'Deactivated', value: patient.deactivated_at ? formatDateTime(patient.deactivated_at) : null },
              { label: 'Reason', value: patient.deactivation_reason, wide: true },
            ] : []),
          ]} />
        </Card>
        <Card title="Emergency contact" actions={<ProvenanceTag kind="record" />}>
          <DescriptionList columns={2} items={[
            { label: 'Name', value: patient.emergency_contact_name },
            { label: 'Relationship', value: patient.emergency_contact_relationship },
            { label: 'Phone', value: patient.emergency_contact_phone },
          ]} />
        </Card>
      </div>

      {canReadClinical('observation.view') ? <LatestVitalsCard patientId={patient.id} to={`${base}/vitals`} /> : null}
      {canReadClinical('condition.view') ? <ConditionsCard patientId={patient.id} to={`${base}/conditions`} /> : null}
      {canReadClinical('encounter.view') ? <EncountersCard patientId={patient.id} to={`${base}/encounters`} /> : null}
      {canReadClinical('clinical_note.view') ? <NotesCard patientId={patient.id} to={`${base}/notes`} /> : null}
    </div>
  )
}

function ViewAll({ to }: { to: string }) {
  return <LinkButton to={to} variant="ghost" size="sm" iconRight="arrowRight">View all</LinkButton>
}

function LatestVitalsCard({ patientId, to }: { patientId: string; to: string }) {
  const result = useQuery((s) => clinicalApi.observations(patientId, { limit: 100 }, s), [patientId])
  const rows = result.data ? latestVitals(result.data.items) : []
  const rank = (row: (typeof rows)[number]) => {
    const index = VITAL_ORDER.indexOf(row.kind === 'bp' ? 'blood_pressure' : row.observation.code)
    return index === -1 ? VITAL_ORDER.length : index
  }
  rows.sort((a, b) => rank(a) - rank(b))
  return (
    <Card className="span-12" title="Latest vitals & observations" description="Most recent value of each measurement, from the latest 100 readings"
      padding="none" actions={<ViewAll to={to} />}>
      {result.error ? <ErrorState compact error={result.error} onRetry={result.reload} />
        : result.loading ? <LoadingState rows={2} />
          : rows.length === 0 ? <EmptyState compact icon="pulse" title="No observations recorded" />
            : (
              <div className="vitals-grid vitals-grid--inset">
                {rows.slice(0, 8).map((row) => {
                  const o = row.kind === 'bp' ? row.systolic : row.observation
                  return (
                    <div className="vital" key={row.key}>
                      <span className="vital__label">{row.kind === 'bp' ? 'Blood pressure' : o.display}</span>
                      <span className="vital__value tabular">{row.kind === 'bp' ? bloodPressureValue(row.systolic, row.diastolic) : observationValue(o)}</span>
                      <span className="vital__time">{formatShortDateTime(o.effective_at)}</span>
                    </div>
                  )
                })}
              </div>
            )}
    </Card>
  )
}

function ConditionsCard({ patientId, to }: { patientId: string; to: string }) {
  const active = useQuery((s) => clinicalApi.conditions(patientId, { status: 'ACTIVE', limit: 5 }, s), [patientId])
  const suspected = useQuery((s) => clinicalApi.conditions(patientId, { status: 'SUSPECTED', limit: 5 }, s), [patientId])
  const items = [...(active.data?.items ?? []), ...(suspected.data?.items ?? [])]
  const error = active.error ?? suspected.error
  return (
    <Card className="span-6" title="Active & suspected conditions" padding="none" actions={<ViewAll to={to} />}>
      {error ? <ErrorState compact error={error} />
        : active.loading || suspected.loading ? <LoadingState rows={2} />
          : items.length === 0 ? <EmptyState compact icon="document" title="No active or suspected conditions documented" />
            : (
              <ul className="mini-list">
                {items.map((c) => (
                  <li key={c.id}>
                    <span className="mini-list__main">
                      <span className="mini-list__title">{c.name}</span>
                      <span className="mini-list__sub">Recorded {formatDate(c.recorded_at)}</span>
                    </span>
                    <span className="mini-list__side"><StatusBadge status={c.status} size="sm" /></span>
                  </li>
                ))}
              </ul>
            )}
    </Card>
  )
}

function EncountersCard({ patientId, to }: { patientId: string; to: string }) {
  const result = useQuery((s) => clinicalApi.encounters(patientId, { limit: 4 }, s), [patientId])
  return (
    <Card className="span-6" title="Recent encounters" padding="none" actions={<ViewAll to={to} />}>
      {result.error ? <ErrorState compact error={result.error} />
        : result.loading ? <LoadingState rows={2} />
          : !result.data || result.data.items.length === 0 ? <EmptyState compact icon="clinical" title="No encounters recorded" />
            : (
              <ul className="mini-list">
                {result.data.items.map((e) => (
                  <li key={e.id}>
                    <span className="mini-list__main">
                      <span className="mini-list__title">{humanize(e.encounter_type)} · {e.reason}</span>
                      <span className="mini-list__sub">{formatDateTime(e.start_at)}</span>
                    </span>
                    <span className="mini-list__side"><StatusBadge status={e.status} size="sm" /></span>
                  </li>
                ))}
              </ul>
            )}
    </Card>
  )
}

function NotesCard({ patientId, to }: { patientId: string; to: string }) {
  const result = useQuery((s) => clinicalApi.notes(patientId, { limit: 1 }, s), [patientId])
  const note = result.data?.items[0]
  return (
    <Card className="span-12" title="Latest clinical note" padding="none" actions={<ViewAll to={to} />}>
      {result.error ? <ErrorState compact error={result.error} />
        : result.loading ? <LoadingState rows={2} />
          : !note ? <EmptyState compact icon="edit" title="No clinical notes recorded" />
            : (
              <div className="note-card">
                <div className="note-card__head">
                  <StatusBadge status={note.note_type} label={humanize(note.note_type)} size="sm" />
                  <span className="note-card__author">{note.author_name}</span>
                  <span className="note-card__time">{formatDateTime(note.authored_at)}</span>
                </div>
                <div className="note-card__body note-card__body--clamped">{note.content}</div>
              </div>
            )}
    </Card>
  )
}
