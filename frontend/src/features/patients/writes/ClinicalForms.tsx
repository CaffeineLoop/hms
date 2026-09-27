/**
 * UI-3 clinical documentation writes inside the patient record: encounters (create + lifecycle actions), vitals,
 * clinical notes, conditions and allergies. Every write is a call to the existing HMS endpoint; the backend validates
 * values, lifecycle transitions and permissions, and binds authorship to the signed-in user. After a successful write
 * the UI navigates/reloads so what is shown always comes from the API (no optimistic clinical state).
 */
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { clinicalApi, clinicalWriteApi } from '../../../api/endpoints'
import type { Allergy, Condition, Encounter } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import { Alert, Button, Card, EmptyState, Field, Input, LinkButton, Select, Textarea } from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import { describeWriteError, useSubmit } from '../../../hooks/useSubmit'
import { unitSymbol } from '../../../lib/clinical'
import { dateInputToIso, localInputToIso, optionalText, parseNumber } from '../../../lib/forms'
import { formatDateTime, humanize } from '../../../lib/format'
import { ActionDialog, AuthorStatement, ProblemAlert, StaffSelect } from '../../writes/WriteControls'
import { usePatientRecord } from '../patientContext'
import { SectionHead } from '../shared'
import '../../writes/writes.css'

// ---------------------------------------------------------------- shared pieces

/** Shows the page only to users holding the write permission (the backend still decides; it returns 403 otherwise). */
export function WriteGuard({ permission, children }: { permission: string; children: ReactNode }) {
  const { hasAllScope } = useAuth()
  if (!hasAllScope(permission)) {
    return <Card><EmptyState icon="lock" title="Not available for your role"
      description={`Recording this requires the ${permission} permission for all patients.`} /></Card>
  }
  return <>{children}</>
}

/** Success message passed via navigation state after a write (the list below it is re-read from the API). */
export function SavedNotice() {
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  return notice ? <div className="plist__notice"><Alert tone="success">{notice}</Alert></div> : null
}

const RECORDABLE = new Set(['IN_PROGRESS', 'FINISHED'])

/**
 * The patient's encounters that can hold clinical records (the backend accepts in-progress and finished encounters
 * only and rejects anything else).
 */
function EncounterSelect({ value, onChange, error, required, label = 'Encounter', disabled }: {
  value: string; onChange: (value: string) => void; error?: string; required?: boolean; label?: string; disabled?: boolean
}) {
  const { patient } = usePatientRecord()
  const encounters = useQuery((s) => clinicalApi.encounters(patient.id, { limit: 50 }, s), [patient.id])
  const options = (encounters.data?.items ?? []).filter((e) => RECORDABLE.has(e.status))
  return (
    <Field label={label} required={required} error={error ?? encounters.error?.message}
      hint="In-progress and finished encounters of this patient">
      <Select value={value} onChange={(e) => onChange(e.target.value)} disabled={encounters.loading || disabled}>
        <option value="">{encounters.loading ? 'Loading…' : required ? 'Select an encounter…' : 'Not linked to an encounter'}</option>
        {options.map((e) => (
          <option key={e.id} value={e.id}>{humanize(e.encounter_type)} · {formatDateTime(e.start_at)} · {humanize(e.status)} — {e.reason}</option>
        ))}
      </Select>
    </Field>
  )
}

function FormPage({ title, description, children, onSubmit }: {
  title: string; description: string; children: ReactNode; onSubmit: (event: FormEvent) => void
}) {
  return (
    <>
      <SectionHead title={title} meta={<span>{description}</span>} />
      <form className="form-layout" onSubmit={onSubmit} noValidate>{children}</form>
    </>
  )
}

function Actions({ cancelTo, submitting, label }: { cancelTo: string; submitting: boolean; label: string }) {
  return (
    <div className="form-actions">
      <LinkButton to={cancelTo} variant="secondary">Cancel</LinkButton>
      <Button type="submit" variant="primary" loading={submitting} icon="checkCircle">{label}</Button>
    </div>
  )
}

const CODE_SYSTEMS = {
  condition: [{ value: 'http://snomed.info/sct', label: 'SNOMED CT' }, { value: 'http://hl7.org/fhir/sid/icd-10', label: 'ICD-10' }],
  allergy: [{ value: 'http://www.nlm.nih.gov/research/umls/rxnorm', label: 'RxNorm' }, { value: 'http://snomed.info/sct', label: 'SNOMED CT' }],
}

// ---------------------------------------------------------------- encounters

export function NewEncounterPage() {
  const { patient, recordChanged } = usePatientRecord()
  const navigate = useNavigate()
  const base = `/patients/${patient.id}/encounters`
  const [form, setForm] = useState({ encounter_type: '', status: 'IN_PROGRESS', start_at: '', end_at: '', reason: '', summary: '', attending_staff_id: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!form.encounter_type) missing.encounter_type = 'Select the encounter type.'
    if (!form.reason.trim()) missing.reason = 'Enter the reason for the visit.'
    if (Object.keys(missing).length) return reject(missing, 'The encounter has not been created.')
    const created = await run(() => clinicalWriteApi.createEncounter(patient.id, {
      encounter_type: form.encounter_type, status: form.status, reason: form.reason.trim(),
      start_at: localInputToIso(form.start_at), end_at: form.status === 'FINISHED' ? localInputToIso(form.end_at) : null,
      summary: form.status === 'FINISHED' ? optionalText(form.summary) : null,
      attending_staff_id: form.attending_staff_id || null,
    }))
    if (created) {
      recordChanged()
      navigate(`${base}/${created.id}`, { state: { notice: `${humanize(created.encounter_type)} encounter created (${humanize(created.status)}).` } })
    }
  }

  return (
    <WriteGuard permission="encounter.create">
      <FormPage title="New encounter" description="Open a visit now, plan one, or document a past visit" onSubmit={onSubmit}>
        <ProblemAlert problem={problem} />
        <Card title="Encounter">
          <div className="form-grid">
            <Field label="Type" required error={errors.encounter_type}>
              <Select value={form.encounter_type} onChange={(e) => set('encounter_type')(e.target.value)}>
                <option value="">Select…</option>
                {['OPD', 'EMERGENCY', 'INPATIENT', 'FOLLOW_UP'].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
              </Select>
            </Field>
            <Field label="Status" required error={errors.status}>
              <Select value={form.status} onChange={(e) => set('status')(e.target.value)}>
                <option value="IN_PROGRESS">In progress — the visit is happening now</option>
                <option value="PLANNED">Planned — a future visit</option>
                <option value="FINISHED">Finished — document a past visit</option>
              </Select>
            </Field>
            <Field label="Start" error={errors.start_at} hint={form.status === 'IN_PROGRESS' ? 'Leave empty to start now' : 'Required for planned and finished encounters'}>
              <Input type="datetime-local" value={form.start_at} onChange={(e) => set('start_at')(e.target.value)} />
            </Field>
            {form.status === 'FINISHED' ? (
              <Field label="End" error={errors.end_at}>
                <Input type="datetime-local" value={form.end_at} onChange={(e) => set('end_at')(e.target.value)} />
              </Field>
            ) : <div />}
            <div className="form-grid__wide">
              <Field label="Reason for visit" required error={errors.reason}>
                <Input value={form.reason} onChange={(e) => set('reason')(e.target.value)} maxLength={500} />
              </Field>
            </div>
            {form.status === 'FINISHED' ? (
              <div className="form-grid__wide">
                <Field label="Summary" error={errors.summary}><Textarea value={form.summary} onChange={(e) => set('summary')(e.target.value)} rows={4} /></Field>
              </div>
            ) : null}
            <StaffSelect label="Attending clinician" value={form.attending_staff_id} onChange={set('attending_staff_id')}
              error={errors.attending_staff_id} hint="Assignment only — optional" />
          </div>
        </Card>
        <Actions cancelTo={base} submitting={submitting} label="Create encounter" />
      </FormPage>
    </WriteGuard>
  )
}

/** Lifecycle actions on an encounter (start / finish / cancel), offered for the statuses the backend accepts them in. */
export function EncounterActions({ encounter, onChanged }: { encounter: Encounter; onChanged: () => void }) {
  const { hasAllScope } = useAuth()
  const { patient, recordChanged } = usePatientRecord()
  const [dialog, setDialog] = useState<null | 'start' | 'finish' | 'cancel'>(null)
  const done = () => { recordChanged(); onChanged() }
  const recordable = RECORDABLE.has(encounter.status)
  const base = `/patients/${patient.id}`
  const canEdit = hasAllScope('encounter.edit')
  return (
    <div className="action-bar">
      {recordable && hasAllScope('observation.create') ? <LinkButton size="sm" to={`${base}/vitals/new?encounter=${encounter.id}`} icon="pulse">Record vitals</LinkButton> : null}
      {recordable && hasAllScope('clinical_note.create') ? <LinkButton size="sm" to={`${base}/notes/new?encounter=${encounter.id}`} icon="edit">Write note</LinkButton> : null}
      {canEdit && encounter.status === 'PLANNED' ? <Button size="sm" variant="primary" onClick={() => setDialog('start')}>Start encounter</Button> : null}
      {canEdit && encounter.status === 'IN_PROGRESS' ? <Button size="sm" variant="primary" onClick={() => setDialog('finish')}>Finish encounter</Button> : null}
      {canEdit && (encounter.status === 'PLANNED' || encounter.status === 'IN_PROGRESS')
        ? <Button size="sm" variant="danger-ghost" onClick={() => setDialog('cancel')}>Cancel encounter</Button> : null}
      <ActionDialog open={dialog === 'start'} title="Start encounter" confirmLabel="Start encounter" onClose={() => setDialog(null)} onDone={done}
        description="The encounter becomes in progress. Leave the time empty to use now."
        fields={[{ name: 'start_at', label: 'Actual start', kind: 'datetime' }]}
        submit={(v) => clinicalWriteApi.encounterAction(encounter.id, 'start', { start_at: localInputToIso(v.start_at) })} />
      <ActionDialog open={dialog === 'finish'} title="Finish encounter" confirmLabel="Finish encounter" onClose={() => setDialog(null)} onDone={done}
        description="The encounter is closed. Leave the time empty to use now."
        fields={[{ name: 'end_at', label: 'End', kind: 'datetime' }, { name: 'summary', label: 'Summary', kind: 'textarea' }]}
        submit={(v) => clinicalWriteApi.encounterAction(encounter.id, 'finish', { end_at: localInputToIso(v.end_at), summary: optionalText(v.summary) })} />
      <ActionDialog open={dialog === 'cancel'} title="Cancel encounter" confirmLabel="Cancel encounter" tone="danger" onClose={() => setDialog(null)} onDone={done}
        description="A cancelled encounter cannot be reopened and cannot hold clinical records."
        fields={[{ name: 'reason', label: 'Reason', kind: 'textarea', required: true }]}
        submit={(v) => clinicalWriteApi.encounterAction(encounter.id, 'cancel', { reason: v.reason.trim() })} />
    </div>
  )
}

// ---------------------------------------------------------------- vitals

interface VitalField { code: string; label: string; units: string[] }
const VITAL_FIELDS: VitalField[] = [
  { code: 'heart_rate', label: 'Heart rate', units: ['/min'] },
  { code: 'respiratory_rate', label: 'Respiratory rate', units: ['/min'] },
  { code: 'oxygen_saturation', label: 'Oxygen saturation (SpO₂)', units: ['%'] },
  { code: 'body_temperature', label: 'Body temperature', units: ['Cel', '[degF]'] },
  { code: 'body_weight', label: 'Body weight', units: ['kg', '[lb_av]'] },
  { code: 'body_height', label: 'Body height', units: ['cm'] },
  { code: 'blood_glucose', label: 'Blood glucose', units: ['mmol/L', 'mg/dL'] },
]
const SYS = 'systolic_blood_pressure'
const DIA = 'diastolic_blood_pressure'

interface PlannedObservation { code: string; label: string; value: number; unit: string }
type Outcome = { item: PlannedObservation; state: 'saved' | 'failed' | 'skipped'; message?: string }

/**
 * Record a set of vital signs taken at one time. Each measurement is its own observation (the HMS model); blood
 * pressure is stored as a systolic + diastolic pair sharing the same time and encounter, which is how it is paired
 * for display. Values and units are sent as entered — plausibility and unit rules are the backend's.
 * Measurements are sent one by one (BP first) and sending stops at the first rejection, so a rejected value never
 * leaves later measurements half-recorded; anything already saved is reported and removed from the form.
 */
export function RecordVitalsPage() {
  const { patient, recordChanged } = usePatientRecord()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const base = `/patients/${patient.id}/vitals`
  const [encounterId, setEncounterId] = useState(params.get('encounter') ?? '')
  // Empty = the moment of saving (a minute-rounded default could fall before an encounter that just started).
  const [effective, setEffective] = useState('')
  const [pinnedAt, setPinnedAt] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [units, setUnits] = useState<Record<string, string>>(() => Object.fromEntries(VITAL_FIELDS.map((f) => [f.code, f.units[0]])))
  const [notes, setNotes] = useState('')
  const [outcomes, setOutcomes] = useState<Outcome[] | null>(null)
  // After a partial save, the BP half already stored; the other half may then be sent alone to complete the pair.
  const [savedHalf, setSavedHalf] = useState<typeof SYS | typeof DIA | null>(null)
  const { submitting, problem, errors, reject, reset, clearField, setProblem } = useSubmit()
  const [sending, setSending] = useState(false)
  const setValue = (code: string, value: string) => { setValues((v) => ({ ...v, [code]: value })); clearField(code) }

  function plan(): PlannedObservation[] | null {
    const fieldErrors: Record<string, string> = {}
    const planned: PlannedObservation[] = []
    const sys = values[SYS] ?? ''
    const dia = values[DIA] ?? ''
    if (sys.trim() || dia.trim()) {
      if (!sys.trim() && savedHalf !== SYS) fieldErrors[SYS] = 'Enter the systolic value to record a blood pressure.'
      if (!dia.trim() && savedHalf !== DIA) fieldErrors[DIA] = 'Enter the diastolic value to record a blood pressure.'
    }
    const numeric = (code: string, label: string, unit: string) => {
      const raw = values[code] ?? ''
      const value = parseNumber(raw)
      if (value === undefined) return
      if (Number.isNaN(value)) { fieldErrors[code] = 'Enter a number.'; return }
      planned.push({ code, label, value, unit })
    }
    numeric(SYS, 'Systolic blood pressure', 'mm[Hg]')
    numeric(DIA, 'Diastolic blood pressure', 'mm[Hg]')
    for (const f of VITAL_FIELDS) numeric(f.code, f.label, units[f.code])
    if (!planned.length && !Object.keys(fieldErrors).length) fieldErrors.form = 'Enter at least one measurement.'
    if (Object.keys(fieldErrors).length) {
      reject(fieldErrors, fieldErrors.form ?? 'Nothing was sent to the HMS.')
      return null
    }
    return planned
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    reset()
    setOutcomes(null)
    const planned = plan()
    if (!planned) return
    // A pending BP half is completed with exactly the time its partner was saved with, so the two pair.
    const effectiveAt = (savedHalf && pinnedAt) || localInputToIso(effective) || new Date().toISOString()
    const results: Outcome[] = []
    setSending(true)
    let failed = false
    for (const item of planned) {
      if (failed) { results.push({ item, state: 'skipped' }); continue }
      try {
        await clinicalWriteApi.createObservation(patient.id, {
          code: item.code, value_numeric: item.value, unit: item.unit, effective_at: effectiveAt,
          encounter_id: encounterId || null, notes: optionalText(notes),
        })
        results.push({ item, state: 'saved' })
      } catch (error) {
        failed = true
        // Per-measurement message: other measurements of this set may already be saved, so no "nothing was saved".
        const { problem: p } = describeWriteError(error)
        const message = p.message.replace(/ (Nothing was saved|Nothing was changed)\.$/, '')
        results.push({ item, state: 'failed', message })
        setProblem({ ...p, title: `${item.label} was not saved`, message })
      }
    }
    setSending(false)
    const saved = results.filter((r) => r.state === 'saved')
    if (saved.length) recordChanged()
    const savedCodes = new Set(saved.map((r) => r.item.code))
    if (savedCodes.has(SYS) !== savedCodes.has(DIA)) { setSavedHalf(savedCodes.has(SYS) ? SYS : DIA); setPinnedAt(effectiveAt) }
    else if (savedCodes.has(SYS)) setSavedHalf(null)
    if (!failed) {
      navigate(base, { state: { notice: `${saved.length} measurement${saved.length === 1 ? '' : 's'} recorded.` } })
      return
    }
    // keep only what still needs saving; the same time/encounter is kept so a BP half re-pairs when completed
    setValues((current) => {
      const next = { ...current }
      for (const r of saved) delete next[r.item.code]
      return next
    })
    setOutcomes(results)
  }

  const savedSystolicOnly = savedHalf === SYS
  const busy = sending || submitting

  return (
    <WriteGuard permission="observation.create">
      <FormPage title="Record vital signs" description="Values are stored exactly as entered; the HMS checks units and plausibility" onSubmit={onSubmit}>
        <ProblemAlert problem={problem} />
        {outcomes ? (
          <Alert tone="warning" title="Some measurements were not saved">
            <ul className="save-report">
              {outcomes.map((o) => (
                <li key={o.item.code}>{o.state === 'saved' ? 'Saved' : o.state === 'failed' ? 'Not saved' : 'Not sent'}: {o.item.label}
                  {' '}{o.item.value} {unitSymbol(o.item.unit)}{o.message ? ` — ${o.message}` : ''}</li>
              ))}
            </ul>
            {savedSystolicOnly ? <p>The systolic value was saved without its diastolic pair. Correct the diastolic value and save again;
              the time and encounter are locked so the two halves pair as one reading.</p> : null}
            {savedHalf === DIA ? <p>The diastolic value was saved without its systolic pair. Correct the systolic value and save again;
              the time and encounter are locked so the two halves pair as one reading.</p> : null}
            <p>Saved measurements have been removed from the form. Correct the rest and save again.</p>
          </Alert>
        ) : null}
        <AuthorStatement />
        <Card title="When and where">
          <div className="form-grid">
            <Field label="Taken at" error={errors.effective_at} hint={savedHalf && pinnedAt ? `Locked to ${formatDateTime(pinnedAt)}, the time of the saved blood-pressure half` : 'Leave empty to use the time of saving'}>
              <Input type="datetime-local" value={effective} disabled={Boolean(savedHalf)}
                onChange={(e) => { setEffective(e.target.value); clearField('effective_at') }} />
            </Field>
            <EncounterSelect value={encounterId} onChange={setEncounterId} error={errors.encounter_id} disabled={Boolean(savedHalf)} />
          </div>
        </Card>
        <Card title="Measurements" description="Leave blank what was not measured">
          <div className="vitals-form">
            <div className="vitals-form__row">
              <span className="vitals-form__label">Blood pressure</span>
              <div className="vitals-form__inputs">
                <Field label="Systolic (mmHg)" error={errors[SYS]}><Input inputMode="decimal" value={values[SYS] ?? ''} onChange={(e) => setValue(SYS, e.target.value)} /></Field>
                <Field label="Diastolic (mmHg)" error={errors[DIA]}><Input inputMode="decimal" value={values[DIA] ?? ''} onChange={(e) => setValue(DIA, e.target.value)} /></Field>
              </div>
            </div>
            {VITAL_FIELDS.map((f) => (
              <div className="vitals-form__row" key={f.code}>
                <span className="vitals-form__label">{f.label}</span>
                <div className="vitals-form__inputs">
                  <Field label="Value" error={errors[f.code]}>
                    <Input inputMode="decimal" aria-label={f.label} value={values[f.code] ?? ''} onChange={(e) => setValue(f.code, e.target.value)} />
                  </Field>
                  <Field label="Unit">
                    <Select value={units[f.code]} onChange={(e) => setUnits((u) => ({ ...u, [f.code]: e.target.value }))} disabled={f.units.length === 1}
                      aria-label={`${f.label} unit`}>
                      {f.units.map((u) => <option key={u} value={u}>{unitSymbol(u)}</option>)}
                    </Select>
                  </Field>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Notes" description="Optional; stored with each measurement of this set">
          <Field label="Notes" error={errors.notes}><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={1000} /></Field>
        </Card>
        <Actions cancelTo={base} submitting={busy} label="Save measurements" />
      </FormPage>
    </WriteGuard>
  )
}

// ---------------------------------------------------------------- clinical notes

const NOTE_TYPES = ['PROGRESS', 'HISTORY_AND_PHYSICAL', 'CONSULTATION', 'NURSING', 'PROCEDURE', 'DISCHARGE_SUMMARY', 'OTHER']

export function NewNotePage() {
  const { patient, recordChanged } = usePatientRecord()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const base = `/patients/${patient.id}/notes`
  const [form, setForm] = useState({ encounter_id: params.get('encounter') ?? '', note_type: '', content: '', authored_at: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!form.encounter_id) missing.encounter_id = 'Select the encounter this note belongs to.'
    if (!form.note_type) missing.note_type = 'Select the note type.'
    if (!form.content.trim()) missing.content = 'Write the note.'
    if (Object.keys(missing).length) return reject(missing, 'The note has not been saved.')
    // No author fields are sent: the backend records the signed-in user as the author.
    const created = await run(() => clinicalWriteApi.createNote(patient.id, {
      encounter_id: form.encounter_id, note_type: form.note_type, content: form.content, authored_at: localInputToIso(form.authored_at),
    }))
    if (created) {
      recordChanged()
      navigate(base, { state: { notice: `${humanize(created.note_type)} note saved, authored by ${created.author_name}.` } })
    }
  }

  return (
    <WriteGuard permission="clinical_note.create">
      <FormPage title="Write clinical note" description="Notes are permanent once saved; they cannot be edited or deleted" onSubmit={onSubmit}>
        <ProblemAlert problem={problem} />
        <AuthorStatement verb="Authored" />
        <Card title="Note">
          <div className="form-grid">
            <EncounterSelect required value={form.encounter_id} onChange={set('encounter_id')} error={errors.encounter_id} />
            <Field label="Note type" required error={errors.note_type}>
              <Select value={form.note_type} onChange={(e) => set('note_type')(e.target.value)}>
                <option value="">Select…</option>
                {NOTE_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
              </Select>
            </Field>
            <div className="form-grid__wide">
              <Field label="Content" required error={errors.content}>
                <Textarea value={form.content} onChange={(e) => set('content')(e.target.value)} rows={10} />
              </Field>
            </div>
            <Field label="Authored at" error={errors.authored_at} hint="Leave empty to use now">
              <Input type="datetime-local" value={form.authored_at} onChange={(e) => set('authored_at')(e.target.value)} />
            </Field>
          </div>
        </Card>
        <Actions cancelTo={base} submitting={submitting} label="Save note" />
      </FormPage>
    </WriteGuard>
  )
}

// ---------------------------------------------------------------- conditions

const CONDITION_STATUSES = ['SUSPECTED', 'ACTIVE', 'RESOLVED', 'HISTORICAL']

export function NewConditionPage() {
  const { patient, recordChanged } = usePatientRecord()
  const navigate = useNavigate()
  const base = `/patients/${patient.id}/conditions`
  const [form, setForm] = useState({ name: '', status: 'ACTIVE', onset_at: '', resolved_at: '', code_system: '', code: '', encounter_id: '', notes: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }
  const resolvedApplies = form.status === 'RESOLVED' || form.status === 'HISTORICAL'

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!form.name.trim()) return reject({ name: 'Enter the condition.' }, 'The condition has not been saved.')
    const created = await run(() => clinicalWriteApi.createCondition(patient.id, {
      name: form.name.trim(), status: form.status, onset_at: dateInputToIso(form.onset_at),
      resolved_at: resolvedApplies ? dateInputToIso(form.resolved_at) : null,
      code_system: form.code_system || null, code: optionalText(form.code), encounter_id: form.encounter_id || null,
      notes: optionalText(form.notes),
    }))
    if (created) {
      recordChanged()
      navigate(base, { state: { notice: `Condition “${created.name}” recorded (${humanize(created.status)}).` } })
    }
  }

  return (
    <WriteGuard permission="condition.create">
      <FormPage title="Add condition" description="Documented by you — the HMS never adds conditions automatically" onSubmit={onSubmit}>
        <ProblemAlert problem={problem} />
        <AuthorStatement />
        <Card title="Condition">
          <div className="form-grid">
            <div className="form-grid__wide">
              <Field label="Condition" required error={errors.name}><Input value={form.name} onChange={(e) => set('name')(e.target.value)} maxLength={255} /></Field>
            </div>
            <Field label="Status" required error={errors.status}>
              <Select value={form.status} onChange={(e) => set('status')(e.target.value)}>
                {CONDITION_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            </Field>
            <Field label="Onset" error={errors.onset_at}><Input type="date" value={form.onset_at} onChange={(e) => set('onset_at')(e.target.value)} /></Field>
            {resolvedApplies ? (
              <Field label="Resolved" error={errors.resolved_at}><Input type="date" value={form.resolved_at} onChange={(e) => set('resolved_at')(e.target.value)} /></Field>
            ) : null}
            <EncounterSelect value={form.encounter_id} onChange={set('encounter_id')} error={errors.encounter_id} />
            <Field label="Code system" error={errors.code_system}>
              <Select value={form.code_system} onChange={(e) => set('code_system')(e.target.value)}>
                <option value="">Not coded</option>
                {CODE_SYSTEMS.condition.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </Select>
            </Field>
            <Field label="Code" error={errors.code}><Input value={form.code} onChange={(e) => set('code')(e.target.value)} maxLength={64} /></Field>
            <div className="form-grid__wide">
              <Field label="Notes" error={errors.notes}><Textarea value={form.notes} onChange={(e) => set('notes')(e.target.value)} rows={3} /></Field>
            </div>
          </div>
        </Card>
        <Actions cancelTo={base} submitting={submitting} label="Save condition" />
      </FormPage>
    </WriteGuard>
  )
}

export function UpdateConditionDialog({ condition, onClose, onDone }: { condition: Condition | null; onClose: () => void; onDone: () => void }) {
  return (
    <ActionDialog key={condition?.id ?? 'closed'} open={Boolean(condition)} title={`Update condition: ${condition?.name ?? ''}`} confirmLabel="Save update"
      description={`Current status: ${condition ? humanize(condition.status) : ''}. Only the fields you change are sent; the HMS decides which status changes are allowed.`}
      onClose={onClose} onDone={onDone}
      fields={[
        { name: 'status', label: 'New status', kind: 'select', placeholder: 'No change',
          options: CONDITION_STATUSES.filter((s) => s !== condition?.status).map((s) => ({ value: s, label: humanize(s) })) },
        { name: 'resolved_at', label: 'Resolved at', kind: 'datetime', hint: 'For resolved or historical conditions' },
        { name: 'notes', label: 'Notes', kind: 'textarea', defaultValue: condition?.notes ?? '', hint: 'Replaces the current notes' },
      ]}
      submit={(v) => {
        const body: Record<string, unknown> = {}
        if (v.status) body.status = v.status
        if (v.resolved_at) body.resolved_at = localInputToIso(v.resolved_at)
        if ((v.notes ?? '') !== (condition?.notes ?? '')) body.notes = optionalText(v.notes)
        return clinicalWriteApi.updateCondition(condition!.id, body)
      }} />
  )
}

// ---------------------------------------------------------------- allergies

const ALLERGY_STATUSES = ['ACTIVE', 'INACTIVE', 'RESOLVED']
const SEVERITIES = ['MILD', 'MODERATE', 'SEVERE']

export function NewAllergyPage() {
  const { patient, recordChanged } = usePatientRecord()
  const navigate = useNavigate()
  const base = `/patients/${patient.id}/allergies`
  const [form, setForm] = useState({ substance: '', category: '', severity: '', reaction: '', status: 'ACTIVE', onset_at: '', code_system: '', code: '', encounter_id: '', notes: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!form.substance.trim()) return reject({ substance: 'Enter the substance.' }, 'The allergy has not been saved.')
    const created = await run(() => clinicalWriteApi.createAllergy(patient.id, {
      substance: form.substance.trim(), category: form.category || null, severity: form.severity || null,
      reaction: optionalText(form.reaction), status: form.status, onset_at: dateInputToIso(form.onset_at),
      code_system: form.code_system || null, code: optionalText(form.code), encounter_id: form.encounter_id || null,
      notes: optionalText(form.notes),
    }))
    if (created) {
      recordChanged()
      navigate(base, { state: { notice: `Allergy to ${created.substance} recorded.` } })
    }
  }

  return (
    <WriteGuard permission="allergy.create">
      <FormPage title="Add allergy" description="Documented allergies appear in the patient banner while active" onSubmit={onSubmit}>
        <ProblemAlert problem={problem} />
        <AuthorStatement />
        <Card title="Allergy">
          <div className="form-grid">
            <Field label="Substance" required error={errors.substance}><Input value={form.substance} onChange={(e) => set('substance')(e.target.value)} maxLength={255} /></Field>
            <Field label="Category" error={errors.category}>
              <Select value={form.category} onChange={(e) => set('category')(e.target.value)}>
                <option value="">Not recorded</option>
                {['MEDICATION', 'FOOD', 'ENVIRONMENT', 'BIOLOGIC'].map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
              </Select>
            </Field>
            <Field label="Severity" error={errors.severity}>
              <Select value={form.severity} onChange={(e) => set('severity')(e.target.value)}>
                <option value="">Not recorded</option>
                {SEVERITIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
              </Select>
            </Field>
            <Field label="Status" required error={errors.status}>
              <Select value={form.status} onChange={(e) => set('status')(e.target.value)}>
                {ALLERGY_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            </Field>
            <div className="form-grid__wide">
              <Field label="Reaction" error={errors.reaction}><Input value={form.reaction} onChange={(e) => set('reaction')(e.target.value)} maxLength={500} /></Field>
            </div>
            <Field label="Onset" error={errors.onset_at}><Input type="date" value={form.onset_at} onChange={(e) => set('onset_at')(e.target.value)} /></Field>
            <EncounterSelect value={form.encounter_id} onChange={set('encounter_id')} error={errors.encounter_id} />
            <Field label="Code system" error={errors.code_system}>
              <Select value={form.code_system} onChange={(e) => set('code_system')(e.target.value)}>
                <option value="">Not coded</option>
                {CODE_SYSTEMS.allergy.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </Select>
            </Field>
            <Field label="Code" error={errors.code}><Input value={form.code} onChange={(e) => set('code')(e.target.value)} maxLength={64} /></Field>
            <div className="form-grid__wide">
              <Field label="Notes" error={errors.notes}><Textarea value={form.notes} onChange={(e) => set('notes')(e.target.value)} rows={3} /></Field>
            </div>
          </div>
        </Card>
        <Actions cancelTo={base} submitting={submitting} label="Save allergy" />
      </FormPage>
    </WriteGuard>
  )
}

export function UpdateAllergyDialog({ allergy, onClose, onDone }: { allergy: Allergy | null; onClose: () => void; onDone: () => void }) {
  return (
    <ActionDialog key={allergy?.id ?? 'closed'} open={Boolean(allergy)} title={`Update allergy: ${allergy?.substance ?? ''}`} confirmLabel="Save update"
      description={`Current status: ${allergy ? humanize(allergy.status) : ''}. Only the fields you change are sent; the HMS decides which status changes are allowed.`}
      onClose={onClose} onDone={onDone}
      fields={[
        { name: 'status', label: 'New status', kind: 'select', placeholder: 'No change',
          options: ALLERGY_STATUSES.filter((s) => s !== allergy?.status).map((s) => ({ value: s, label: humanize(s) })) },
        { name: 'severity', label: 'Severity', kind: 'select', placeholder: 'No change',
          options: SEVERITIES.filter((s) => s !== allergy?.severity).map((s) => ({ value: s, label: humanize(s) })) },
        { name: 'reaction', label: 'Reaction', kind: 'text', defaultValue: allergy?.reaction ?? '' },
        { name: 'notes', label: 'Notes', kind: 'textarea', defaultValue: allergy?.notes ?? '', hint: 'Replaces the current notes' },
      ]}
      submit={(v) => {
        const body: Record<string, unknown> = {}
        if (v.status) body.status = v.status
        if (v.severity) body.severity = v.severity
        if ((v.reaction ?? '') !== (allergy?.reaction ?? '')) body.reaction = optionalText(v.reaction)
        if ((v.notes ?? '') !== (allergy?.notes ?? '')) body.notes = optionalText(v.notes)
        return clinicalWriteApi.updateAllergy(allergy!.id, body)
      }} />
  )
}
