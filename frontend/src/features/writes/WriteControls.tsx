/**
 * UI-3 building blocks for write flows: the backend-error alert, the authorship statement, staff/department pickers
 * (assignment fields only — never authorship), a patient picker and a generic lifecycle action dialog.
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { patientsApi, staffApi } from '../../api/endpoints'
import type { Patient } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Alert, Button, Field, Input, Modal, Select, Textarea } from '../../components/ui'
import { useDebounced } from '../../hooks/useDebounced'
import { useQuery } from '../../hooks/useQuery'
import type { FormProblem } from '../../hooks/useSubmit'
import { useSubmit } from '../../hooks/useSubmit'
import { humanize, patientDisplayName } from '../../lib/format'
import './writes.css'

export function ProblemAlert({ problem }: { problem: FormProblem | null }) {
  if (!problem) return null
  return <Alert tone={problem.tone} title={problem.title}>{problem.message}</Alert>
}

/** States who will be recorded as the author: always the signed-in user; it is never selectable. */
export function AuthorStatement({ verb = 'Recorded' }: { verb?: string }) {
  const { user } = useAuth()
  return (
    <p className="author-statement">
      {verb} by <strong>{user?.staff.full_name ?? 'you'}</strong>
      {user?.staff.designation ? <span className="text-muted"> · {humanize(user.staff.designation)}</span> : null}
      <span className="text-muted"> — taken from your signed-in account; it cannot be changed here.</span>
    </p>
  )
}

/** Active departments (staff.view). */
export function DepartmentSelect({ value, onChange, error, required, label = 'Department' }: {
  value: string; onChange: (value: string) => void; error?: string; required?: boolean; label?: string
}) {
  const departments = useQuery((s) => staffApi.departments({ status: 'ACTIVE', limit: 100 }, s), [])
  return (
    <Field label={label} required={required} error={error ?? (departments.error ? departments.error.message : undefined)}>
      <Select value={value} onChange={(e) => onChange(e.target.value)} disabled={departments.loading}>
        <option value="">{departments.loading ? 'Loading…' : required ? 'Select…' : 'Not specified'}</option>
        {departments.data?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </Select>
    </Field>
  )
}

/** Active staff (optionally of one department) for ASSIGNMENT fields. Hidden for users without staff.view. */
export function StaffSelect({ value, onChange, error, label, departmentId, hint }: {
  value: string; onChange: (value: string) => void; error?: string; label: string; departmentId?: string; hint?: string
}) {
  const { can } = useAuth()
  const enabled = can('staff.view')
  const staff = useQuery((s) => staffApi.list({ status: 'ACTIVE', department_id: departmentId || undefined, limit: 100 }, s),
    [departmentId], { enabled })
  if (!enabled) return null
  return (
    <Field label={label} error={error} hint={hint}>
      <Select value={value} onChange={(e) => onChange(e.target.value)} disabled={staff.loading}>
        <option value="">{staff.loading ? 'Loading…' : 'Not assigned'}</option>
        {staff.data?.items.map((m) => <option key={m.id} value={m.id}>{m.full_name} · {humanize(m.designation)}</option>)}
      </Select>
    </Field>
  )
}

/** Search-and-select an active patient (patients API). */
export function PatientPicker({ value, onChange, error }: {
  value: Patient | null; onChange: (patient: Patient | null) => void; error?: string
}) {
  const [q, setQ] = useState('')
  const debounced = useDebounced(q, 300)
  const results = useQuery((s) => patientsApi.list({ q: debounced, status: 'ACTIVE', limit: 6 }, s), [debounced],
    { enabled: !value && debounced.trim().length >= 2 })
  if (value) {
    return (
      <Field label="Patient" required error={error}>
        <div className="picked">
          <span><strong>{patientDisplayName(value)}</strong> <span className="mono text-muted">{value.patient_number}</span></span>
          <Button size="sm" variant="ghost" onClick={() => onChange(null)}>Change</Button>
        </div>
      </Field>
    )
  }
  return (
    <div className="patient-picker">
      <Field label="Patient" required error={error} hint="Search by name, Patient ID, phone or email (2+ characters)">
        <Input type="search" icon="search" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      </Field>
      {results.data ? (
        results.data.items.length ? (
          <ul className="picker-results" aria-label="Matching patients">
            {results.data.items.map((p) => (
              <li key={p.id}><button type="button" className="picker-results__item" onClick={() => onChange(p)}>
                <strong>{patientDisplayName(p)}</strong> <span className="mono text-muted">{p.patient_number}</span>
              </button></li>
            ))}
          </ul>
        ) : <p className="text-muted picker-empty">No active patient matches “{debounced}”.</p>
      ) : null}
    </div>
  )
}

export interface ActionField {
  name: string
  label: string
  kind: 'text' | 'password' | 'textarea' | 'select' | 'datetime' | 'staff' | 'department'
  required?: boolean
  hint?: string
  options?: Array<{ value: string; label: string }>
  /** Label of the empty select option (e.g. "No change"). */
  placeholder?: string
  defaultValue?: string
}

/**
 * A lifecycle action (confirm, finish, cancel, discharge, ...) as a dialog. Fields map 1:1 to the action endpoint
 * body; required fields are only checked for presence. The backend validates the transition; its answer is shown
 * and, on success, the caller reloads from the API.
 */
export function ActionDialog({ open, title, description, confirmLabel, tone = 'primary', fields = [], onClose, submit, onDone, children }: {
  open: boolean; title: string; description?: ReactNode; confirmLabel: string; tone?: 'primary' | 'danger'
  fields?: ActionField[]; onClose: () => void; submit: (values: Record<string, string>) => Promise<unknown>; onDone: () => void
  children?: ReactNode
}) {
  const initial = () => Object.fromEntries(fields.map((f) => [f.name, f.defaultValue ?? '']))
  const [values, setValues] = useState<Record<string, string>>(initial)
  const { submitting, problem, errors, run, reject, reset, clearField } = useSubmit()
  const close = () => { if (!submitting) { setValues(initial()); reset(); onClose() } }
  const set = (name: string) => (value: string) => { setValues((v) => ({ ...v, [name]: value })); clearField(name) }

  async function confirm() {
    const missing = Object.fromEntries(fields.filter((f) => f.required && !values[f.name]?.trim())
      .map((f) => [f.name, `Enter ${f.label.toLowerCase()}.`]))
    if (Object.keys(missing).length) { reject(missing); return }
    const ok = await run(async () => { await submit(values); return true })
    if (ok) { setValues(initial()); reset(); onDone(); onClose() }
  }

  return (
    <Modal open={open} onClose={close} title={title} description={description} dismissible={!submitting}
      footer={<>
        <Button variant="secondary" onClick={close} disabled={submitting}>Back</Button>
        <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={confirm} loading={submitting}>{confirmLabel}</Button>
      </>}>
      <div className="stack">
        <ProblemAlert problem={problem} />
        {children}
        {fields.map((f) => {
          const common = { value: values[f.name] ?? '', onChange: set(f.name), error: errors[f.name] }
          if (f.kind === 'staff') return <StaffSelect key={f.name} label={f.label} hint={f.hint} {...common} />
          if (f.kind === 'department') return <DepartmentSelect key={f.name} label={f.label} required={f.required} {...common} />
          return (
            <Field key={f.name} label={f.label} required={f.required} hint={f.hint} error={errors[f.name]}>
              {f.kind === 'textarea' ? <Textarea value={common.value} onChange={(e) => common.onChange(e.target.value)} rows={4} />
                : f.kind === 'select' ? (
                  <Select value={common.value} onChange={(e) => common.onChange(e.target.value)}>
                    <option value="">{f.placeholder ?? 'Select…'}</option>
                    {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </Select>)
                  : <Input type={f.kind === 'datetime' ? 'datetime-local' : f.kind === 'password' ? 'password' : 'text'} autoComplete={f.kind === 'password' ? 'new-password' : undefined} value={common.value}
                    onChange={(e) => common.onChange(e.target.value)} />}
            </Field>
          )
        })}
      </div>
    </Modal>
  )
}
