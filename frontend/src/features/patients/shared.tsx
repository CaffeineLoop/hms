/** Small building blocks shared by the patient-record sections. */
import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { staffApi } from '../../api/endpoints'
import type { ClinicalNote } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { ApiError } from '../../api/client'
import { Alert, Button, Card, ErrorState, LoadingState, ProvenanceTag, StatusBadge } from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { formatDateTime, humanize } from '../../lib/format'

export function SectionHead({ title, meta, children }: { title: string; meta?: ReactNode; children?: ReactNode }) {
  return (
    <div className="section-head">
      <div className="section-head__text">
        <h2 className="section-head__title">{title}</h2>
        <div className="section-head__meta"><ProvenanceTag kind="record" />{meta}</div>
      </div>
      {children ? <div className="section-filters">{children}</div> : null}
    </div>
  )
}

/**
 * Clinician name for a staff id, via the staff directory. Only requested when the user may view staff
 * (staff.view); otherwise a neutral label is shown — the id is never presented as a name.
 */
export function StaffName({ staffId, fallback = 'Staff member' }: { staffId: string | null; fallback?: string }) {
  const { can } = useAuth()
  const enabled = Boolean(staffId) && can('staff.view')
  const staff = useQuery((s) => staffApi.get(staffId as string, s), [staffId], { enabled })
  if (!staffId) return <span className="text-subtle">Not recorded</span>
  if (!enabled) return <span className="text-muted">{fallback} (name restricted)</span>
  if (staff.loading) return <span className="text-subtle">Loading…</span>
  if (staff.error || !staff.data) return <span className="text-muted">{fallback}</span>
  return <span>{staff.data.full_name}</span>
}

const LONG_NOTE = 600

/** A clinical note exactly as written, with its recorded author and time. Long notes can be expanded. */
export function NoteCard({ note, encounterHref }: { note: ClinicalNote; encounterHref?: string }) {
  const [expanded, setExpanded] = useState(false)
  const long = note.content.length > LONG_NOTE
  return (
    <article className="card note-card" aria-label={`${humanize(note.note_type)} note by ${note.author_name}`}>
      <div className="note-card__head">
        <StatusBadge status={note.note_type} label={humanize(note.note_type)} size="sm" />
        <span className="note-card__author">{note.author_name}</span>
        <time className="note-card__time tabular" dateTime={note.authored_at}>{formatDateTime(note.authored_at)}</time>
      </div>
      <div className={['note-card__body', long && !expanded ? 'note-card__body--clamped' : ''].join(' ')}>{note.content}</div>
      <div className="note-card__foot">
        <ProvenanceTag kind="record" />
        <span className="cluster">
          {encounterHref ? <Link to={encounterHref}>View encounter</Link> : null}
          {long ? <Button size="sm" variant="ghost" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            {expanded ? 'Show less' : 'Show full note'}</Button> : null}
        </span>
      </div>
    </article>
  )
}

export interface LifecycleStep {
  status: string
  label: string
  /** When the record reached this step, if the record stores it. */
  at: string | null
}

/**
 * A record's lifecycle as the HMS stores it: steps up to the current status are complete. A cancelled record shows
 * where it stopped and the recorded reason. Purely descriptive — no actions.
 */
export function Lifecycle({ steps, status, cancelledAt, cancellationReason, label }: {
  steps: readonly LifecycleStep[]; status: string; cancelledAt: string | null; cancellationReason: string | null; label: string
}) {
  const reached = steps.map((step) => Boolean(step.at)).lastIndexOf(true)
  const current = status === 'CANCELLED' ? reached : steps.findIndex((step) => step.status === status)
  return (
    <div className="lifecycle-wrap">
      <ol className="lifecycle" aria-label={label} style={{ '--steps': steps.length } as CSSProperties}>
        {steps.map((step, index) => {
          // The final step (e.g. Released, Completed) and a cancelled record's last reached step are complete, not "current".
          const finished = status === 'CANCELLED' || current === steps.length - 1
          const state = index < current ? 'done' : index === current ? (finished ? 'done' : 'current') : 'pending'
          return (
            <li key={step.status} className={`lifecycle__step lifecycle__step--${state}`}
              aria-current={state === 'current' ? 'step' : undefined}>
              <span className="lifecycle__dot" aria-hidden="true" />
              <span className="lifecycle__label">{step.label}</span>
              <span className="lifecycle__time tabular">{step.at ? formatDateTime(step.at) : state === 'pending' ? '—' : ''}</span>
            </li>
          )
        })}
      </ol>
      {status === 'CANCELLED' ? (
        <Alert tone="warning" title={`Cancelled${cancelledAt ? ` on ${formatDateTime(cancelledAt)}` : ''}`}>
          {cancellationReason ? `Reason recorded: ${cancellationReason}` : 'No reason recorded.'}
        </Alert>
      ) : null}
    </div>
  )
}

/**
 * Loading / 403 / 404 / error handling for a record opened by id inside a patient's record. Records are read by id
 * (the backend authorizes the read); one that belongs to a different patient is never shown under this banner.
 */
export function RecordDetailGate<T extends { patient_id: string }>({ result, patientId, noun, back, children }: {
  result: { data: T | undefined; error: ApiError | null; loading: boolean; reload: () => void }
  patientId: string; noun: string; back: ReactNode; children: (record: T) => ReactNode
}) {
  const notFound = <Alert tone="danger" title={`${noun} not found for this patient`}>
    No {noun.toLowerCase()} with this reference is recorded for this patient. {back}</Alert>
  if (result.error?.status === 404) return notFound
  if (result.error) return <Card>{back}<ErrorState error={result.error} onRetry={result.error.isForbidden ? undefined : result.reload} /></Card>
  if (!result.data) return <LoadingState label={`Loading ${noun.toLowerCase()}…`} />
  if (result.data.patient_id !== patientId) return notFound
  return <>{children(result.data)}</>
}
