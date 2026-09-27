/**
 * Conditions, allergies and clinical notes — documented clinical records, shown exactly as recorded (read-only in
 * UI-1). Nothing here is summarised or reinterpreted; AI suggestions are never mixed into these lists.
 */
import { useState } from 'react'
import { clinicalApi } from '../../../api/endpoints'
import type { Allergy, Condition } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import type { Column } from '../../../components/ui'
import {
  Badge, Button, Card, DataTable, EmptyState, ErrorState, Field, LinkButton, LoadingState, Pagination, Select, StatusBadge,
} from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import { formatDate, humanize } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { NoteCard, SectionHead } from '../shared'
import { SavedNotice, UpdateAllergyDialog, UpdateConditionDialog } from '../writes/ClinicalForms'

const PAGE_SIZE = 20

function coding(system: string | null, code: string | null) {
  if (!code) return null
  const name = system?.includes('snomed') ? 'SNOMED CT' : system?.includes('rxnorm') ? 'RxNorm' : system?.includes('loinc') ? 'LOINC'
    : system ?? 'Code'
  return <span className="cell-sub mono">{name} {code}</span>
}

function StatusFilter({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <Field label="Status">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All statuses</option>
        {options.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
      </Select>
    </Field>
  )
}

export function ConditionsSection() {
  const { patient, recordChanged } = usePatientRecord()
  const { hasAllScope } = useAuth()
  const [editing, setEditing] = useState<Condition | null>(null)
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => clinicalApi.conditions(patient.id, { status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, status, offset])
  const columns: Column<Condition>[] = [
    { key: 'name', header: 'Condition', render: (c) => (
      <span className="cell-stack"><span className="cell-strong">{c.name}</span>{coding(c.code_system, c.code)}
        {c.notes ? <span className="cell-sub">{c.notes}</span> : null}</span>) },
    { key: 'status', header: 'Status', render: (c) => <StatusBadge status={c.status} size="sm" /> },
    { key: 'onset', header: 'Onset', numeric: true, priority: 'secondary', render: (c) => (c.onset_at ? formatDate(c.onset_at) : <span className="text-subtle">—</span>) },
    { key: 'resolved', header: 'Resolved', numeric: true, priority: 'tertiary', render: (c) => (c.resolved_at ? formatDate(c.resolved_at) : <span className="text-subtle">—</span>) },
    { key: 'recorded', header: 'Recorded', numeric: true, render: (c) => formatDate(c.recorded_at) },
    ...(hasAllScope('condition.edit') ? [{ key: 'actions', header: <span className="visually-hidden">Actions</span>, align: 'right' as const,
      render: (c: Condition) => <Button size="sm" variant="ghost" icon="edit" onClick={() => setEditing(c)}>Update</Button> }] : []),
  ]
  return (
    <>
      <SavedNotice />
      <UpdateConditionDialog condition={editing} onClose={() => setEditing(null)} onDone={() => { recordChanged(); result.reload() }} />
      <SectionHead title="Conditions" meta={<span>Documented by clinicians — not AI interpretations</span>}>
        {hasAllScope('condition.create') ? <LinkButton to="new" variant="primary" icon="plus">Add condition</LinkButton> : null}
        <StatusFilter value={status} onChange={(v) => { setStatus(v); setOffset(0) }} options={['ACTIVE', 'SUSPECTED', 'RESOLVED', 'HISTORICAL']} />
      </SectionHead>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Conditions" columns={columns} rows={result.data?.items} rowKey={(c) => c.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="document" title={status ? `No ${humanize(status).toLowerCase()} conditions` : 'No conditions documented'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="conditions" /> : null}
          </>
        )}
      </Card>
    </>
  )
}

const SEVERITY_TONE = { SEVERE: 'danger', MODERATE: 'warning', MILD: 'neutral' } as const

export function AllergiesSection() {
  const { patient, recordChanged } = usePatientRecord()
  const { hasAllScope } = useAuth()
  const [editing, setEditing] = useState<Allergy | null>(null)
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => clinicalApi.allergies(patient.id, { status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, status, offset])
  const columns: Column<Allergy>[] = [
    { key: 'substance', header: 'Substance', render: (a) => (
      <span className="cell-stack"><span className="cell-strong">{a.substance}</span>{coding(a.code_system, a.code)}</span>) },
    { key: 'severity', header: 'Severity', render: (a) => (a.severity
      ? <Badge tone={SEVERITY_TONE[a.severity]} size="sm">{humanize(a.severity)}</Badge> : <span className="text-subtle">Not recorded</span>) },
    { key: 'reaction', header: 'Reaction', render: (a) => (
      <span className="cell-stack"><span>{a.reaction ?? <span className="text-subtle">Not recorded</span>}</span>
        {a.notes ? <span className="cell-sub">{a.notes}</span> : null}</span>) },
    { key: 'category', header: 'Category', priority: 'secondary', render: (a) => (a.category ? humanize(a.category) : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'Status', render: (a) => <StatusBadge status={a.status} size="sm" /> },
    { key: 'recorded', header: 'Recorded', numeric: true, priority: 'tertiary', render: (a) => formatDate(a.recorded_at) },
    ...(hasAllScope('allergy.edit') ? [{ key: 'actions', header: <span className="visually-hidden">Actions</span>, align: 'right' as const,
      render: (a: Allergy) => <Button size="sm" variant="ghost" icon="edit" onClick={() => setEditing(a)}>Update</Button> }] : []),
  ]
  return (
    <>
      <SavedNotice />
      <UpdateAllergyDialog allergy={editing} onClose={() => setEditing(null)} onDone={() => { recordChanged(); result.reload() }} />
      <SectionHead title="Allergies" meta={<span>Documented allergies only</span>}>
        {hasAllScope('allergy.create') ? <LinkButton to="new" variant="primary" icon="plus">Add allergy</LinkButton> : null}
        <StatusFilter value={status} onChange={(v) => { setStatus(v); setOffset(0) }} options={['ACTIVE', 'INACTIVE', 'RESOLVED']} />
      </SectionHead>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Allergies" columns={columns} rows={result.data?.items} rowKey={(a) => a.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="alert" title={status ? `No ${humanize(status).toLowerCase()} allergies documented` : 'No allergies documented'}
                description="“None documented” is not the same as “no known allergies”. Confirm with the patient." />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="allergies" /> : null}
          </>
        )}
      </Card>
    </>
  )
}

export function NotesSection() {
  const { patient } = usePatientRecord()
  const { canReadClinical, hasAllScope } = useAuth()
  const [noteType, setNoteType] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => clinicalApi.notes(patient.id, { note_type: noteType || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, noteType, offset])
  return (
    <>
      <SavedNotice />
      <SectionHead title="Clinical notes" meta={<span>Permanent once saved · attributed to their authors</span>}>
        {hasAllScope('clinical_note.create') ? <LinkButton to="new" variant="primary" icon="plus">Write note</LinkButton> : null}
        <Field label="Note type">
          <Select value={noteType} onChange={(e) => { setNoteType(e.target.value); setOffset(0) }}>
            <option value="">All note types</option>
            {['PROGRESS', 'HISTORY_AND_PHYSICAL', 'CONSULTATION', 'NURSING', 'PROCEDURE', 'DISCHARGE_SUMMARY', 'OTHER']
              .map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
        </Field>
      </SectionHead>
      {result.error ? <Card><ErrorState error={result.error} onRetry={result.reload} /></Card>
        : result.loading && !result.data ? <Card padding="none"><LoadingState rows={4} label="Loading notes" /></Card>
          : !result.data || result.data.items.length === 0
            ? <Card><EmptyState icon="edit" title={noteType ? 'No notes of this type' : 'No clinical notes recorded'} /></Card>
            : (
              <div className="notes-list">
                {result.data.items.map((n) => (
                  <NoteCard key={n.id} note={n}
                    encounterHref={canReadClinical('encounter.view') ? `/patients/${patient.id}/encounters/${n.encounter_id}` : undefined} />
                ))}
                <Card padding="none"><Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="notes" /></Card>
              </div>
            )}
    </>
  )
}
