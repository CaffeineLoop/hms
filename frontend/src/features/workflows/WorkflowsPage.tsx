/**
 * UI-3 Workflows module: appointments, admissions and workflow tasks, with the lifecycle actions the backend exposes.
 * Buttons are offered for the statuses where the backend accepts the action (a display hint only — the backend
 * validates every transition and returns 409 otherwise). Staff/department fields are assignments, never authorship:
 * the requester/approver/transferring clinician/task creator are bound by the backend to the signed-in user.
 * After every action the list is re-read from the API.
 */
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { workflowApi } from '../../api/endpoints'
import type { AdmissionAction, AppointmentAction, TaskAction } from '../../api/endpoints'
import type { Admission, Appointment, Patient, WorkflowTask } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { Column } from '../../components/ui'
import {
  Alert, Button, Card, DataTable, EmptyState, ErrorState, Field, Input, LinkButton, PageHeader, Pagination, Select,
  StatusBadge, Textarea,
} from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { useSubmit } from '../../hooks/useSubmit'
import { localInputToIso, optionalText } from '../../lib/forms'
import { formatDateTime, formatTime, humanize } from '../../lib/format'
import { StaffName } from '../patients/shared'
import type { ActionField } from '../writes/WriteControls'
import { ActionDialog, AuthorStatement, DepartmentSelect, PatientPicker, ProblemAlert, StaffSelect } from '../writes/WriteControls'
import { DepartmentName, PatientName } from './lookups'
import '../patients/patients.css'
import '../writes/writes.css'

const PAGE_SIZE = 20

// ---------------------------------------------------------------- module shell

const TABS = [
  { path: 'appointments', label: 'Appointments', permission: 'appointment.view' },
  { path: 'admissions', label: 'Admissions', permission: 'admission.view' },
  { path: 'tasks', label: 'Tasks', permission: 'workflow.view' },
] as const

export function WorkflowsLayout() {
  const { can } = useAuth()
  const tabs = TABS.filter((t) => can(t.permission))
  return (
    <>
      <PageHeader title="Workflows" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Workflows' }]}
        description="Appointments, admissions and ward tasks. Every action is checked and recorded by the HMS." />
      {tabs.length === 0 ? (
        <Card><EmptyState icon="lock" title="Not available for your role"
          description="Workflows require appointment.view, admission.view or workflow.view." /></Card>
      ) : (
        <>
          <nav className="tabs" aria-label="Workflow areas">
            <div className="tabs__list">
              {tabs.map((t) => (
                <NavLink key={t.path} to={`/workflows/${t.path}`}
                  className={({ isActive }) => ['tabs__tab', isActive ? 'is-selected' : ''].join(' ')}>{t.label}</NavLink>
              ))}
            </div>
          </nav>
          <div className="precord__section"><Outlet /></div>
        </>
      )}
    </>
  )
}

export function WorkflowsIndex() {
  const { can } = useAuth()
  const first = TABS.find((t) => can(t.permission))
  return first ? <Navigate to={`/workflows/${first.path}`} replace /> : null
}

export function AreaGuard({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(permission)) {
    return <Card><EmptyState icon="lock" title="Not available for your role" description={`This requires the ${permission} permission.`} /></Card>
  }
  return <>{children}</>
}

function Notice() {
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  return notice ? <div className="plist__notice"><Alert tone="success">{notice}</Alert></div> : null
}

function dayBounds(day: string): { from: string; to: string } {
  const start = new Date(`${day}T00:00`)
  const end = new Date(start)
  end.setDate(end.getDate() + 1)
  return { from: start.toISOString(), to: new Date(end.getTime() - 1).toISOString() }
}

function todayInput(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface DialogSpec<A extends string> {
  action: A
  title: string
  confirmLabel: string
  description?: string
  tone?: 'primary' | 'danger'
  fields?: ActionField[]
  body?: (values: Record<string, string>) => unknown
}

function RowActions<A extends string>({ specs, available, onRun }: {
  specs: Record<A, DialogSpec<A>>; available: A[]; onRun: (spec: DialogSpec<A>) => void
}) {
  if (!available.length) return <span className="text-subtle">—</span>
  return (
    <span className="action-bar">
      {available.map((a) => (
        <Button key={a} size="sm" variant={specs[a].tone === 'danger' ? 'danger-ghost' : 'secondary'}
          onClick={(e) => { e.stopPropagation(); onRun(specs[a]) }}>{specs[a].confirmLabel}</Button>
      ))}
    </span>
  )
}

const REASON: ActionField = { name: 'reason', label: 'Reason', kind: 'textarea', required: true }

// ---------------------------------------------------------------- appointments

const APPOINTMENT_STATUSES = ['REQUESTED', 'CONFIRMED', 'CHECKED_IN', 'IN_CONSULTATION', 'COMPLETED', 'CANCELLED', 'NO_SHOW']
const APPOINTMENT_ACTIONS: Record<AppointmentAction, DialogSpec<AppointmentAction>> = {
  confirm: { action: 'confirm', title: 'Confirm appointment', confirmLabel: 'Confirm' },
  'check-in': { action: 'check-in', title: 'Check in patient', confirmLabel: 'Check in', description: 'Records that the patient has arrived.' },
  'start-consultation': { action: 'start-consultation', title: 'Start consultation', confirmLabel: 'Start consultation',
    description: 'Opens an in-progress encounter for this visit.',
    fields: [
      { name: 'encounter_type', label: 'Encounter type', kind: 'select', placeholder: 'Outpatient (default)',
        options: [{ value: 'OPD', label: 'Outpatient (OPD)' }, { value: 'FOLLOW_UP', label: 'Follow-up' }] },
      { name: 'attending_staff_id', label: 'Attending clinician', kind: 'staff', hint: "Defaults to the appointment's clinician" },
    ],
    body: (v) => ({ ...(v.encounter_type ? { encounter_type: v.encounter_type } : {}), ...(v.attending_staff_id ? { attending_staff_id: v.attending_staff_id } : {}) }) },
  complete: { action: 'complete', title: 'Complete appointment', confirmLabel: 'Complete',
    fields: [{ name: 'summary', label: 'Summary', kind: 'textarea' }], body: (v) => ({ summary: optionalText(v.summary) }) },
  'no-show': { action: 'no-show', title: 'Mark as no-show', confirmLabel: 'No-show', tone: 'danger', description: 'The patient did not attend.' },
  cancel: { action: 'cancel', title: 'Cancel appointment', confirmLabel: 'Cancel', tone: 'danger', fields: [REASON], body: (v) => ({ reason: v.reason.trim() }) },
}
const APPOINTMENT_AVAILABLE: Record<string, AppointmentAction[]> = {
  REQUESTED: ['confirm', 'cancel'], CONFIRMED: ['check-in', 'no-show', 'cancel'], CHECKED_IN: ['start-consultation', 'cancel'],
  IN_CONSULTATION: ['complete'],
}

export function AppointmentsPanel() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const day = params.get('date') ?? todayInput()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [running, setRunning] = useState<{ spec: DialogSpec<AppointmentAction>; appointment: Appointment } | null>(null)
  const { from, to } = dayBounds(day)
  const result = useQuery((s) => workflowApi.appointments({ scheduled_from: from, scheduled_to: to, status: status || undefined,
    limit: PAGE_SIZE, offset }, s), [from, to, status, offset])
  const manage = can('appointment.manage')

  const columns: Column<Appointment>[] = [
    { key: 'time', header: 'Time', numeric: true, width: 110, render: (a) => <span className="cell-stack"><span className="cell-strong">{formatTime(a.scheduled_start)}</span>
      <span className="cell-sub">{a.duration_minutes} min</span></span> },
    { key: 'patient', header: 'Patient', render: (a) => <PatientName id={a.patient_id} /> },
    { key: 'reason', header: 'Reason', render: (a) => <span className="cell-stack"><span>{a.reason}</span>
      {a.cancellation_reason ? <span className="cell-sub">Cancelled: {a.cancellation_reason}</span> : null}</span> },
    { key: 'clinician', header: 'Clinician', priority: 'secondary', render: (a) => (a.staff_id ? <StaffName staffId={a.staff_id} /> : <span className="text-subtle">—</span>) },
    { key: 'dept', header: 'Department', priority: 'tertiary', render: (a) => <DepartmentName id={a.department_id} /> },
    { key: 'status', header: 'Status', render: (a) => <span className="cell-stack"><StatusBadge status={a.status} size="sm" />
      {a.encounter_id ? <Link className="cell-sub" to={`/patients/${a.patient_id}/encounters/${a.encounter_id}`}>Encounter</Link> : null}</span> },
    ...(manage ? [{ key: 'actions', header: 'Actions', render: (a: Appointment) => (
      <RowActions specs={APPOINTMENT_ACTIONS} available={APPOINTMENT_AVAILABLE[a.status] ?? []} onRun={(spec) => setRunning({ spec, appointment: a })} />) }] : []),
  ]

  return (
    <AreaGuard permission="appointment.view">
      <Notice />
      <div className="section-head">
        <div className="section-head__text"><h2 className="section-head__title">Appointments</h2></div>
        <div className="section-filters">
          <Field label="Date"><Input type="date" value={day} onChange={(e) => { setParams(e.target.value ? { date: e.target.value } : {}, { replace: true }); setOffset(0) }} /></Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All statuses</option>
              {APPOINTMENT_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </Field>
          {manage ? <LinkButton to="/workflows/appointments/new" variant="primary" icon="plus">Book appointment</LinkButton> : null}
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Appointments" columns={columns} rows={result.data?.items} rowKey={(a) => a.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="calendar" title={status ? 'No appointments match this filter' : 'No appointments on this day'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="appointments" /> : null}
          </>
        )}
      </Card>
      {running ? (
        <ActionDialog key={`${running.appointment.id}-${running.spec.action}`} open title={running.spec.title} confirmLabel={running.spec.confirmLabel}
          tone={running.spec.tone} description={running.spec.description} fields={running.spec.fields}
          onClose={() => setRunning(null)} onDone={result.reload}
          submit={(v) => workflowApi.appointmentAction(running.appointment.id, running.spec.action, running.spec.body?.(v))} />
      ) : null}
    </AreaGuard>
  )
}

export function BookAppointmentPage() {
  const navigate = useNavigate()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [form, setForm] = useState({ department_id: '', staff_id: '', reason: '', scheduled_start: '', duration_minutes: '15', notes: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!patient) missing.patient = 'Select the patient.'
    if (!form.department_id) missing.department_id = 'Select the department.'
    if (!form.reason.trim()) missing.reason = 'Enter the reason.'
    if (!form.scheduled_start) missing.scheduled_start = 'Enter the date and time.'
    if (Object.keys(missing).length) return reject(missing, 'The appointment has not been booked.')
    const created = await run(() => workflowApi.bookAppointment(patient!.id, {
      department_id: form.department_id, staff_id: form.staff_id || null, reason: form.reason.trim(),
      scheduled_start: localInputToIso(form.scheduled_start), duration_minutes: Number(form.duration_minutes), notes: optionalText(form.notes),
    }))
    if (created) {
      const day = form.scheduled_start.slice(0, 10)
      navigate(`/workflows/appointments?date=${day}`, { state: { notice: `Appointment booked for ${formatDateTime(created.scheduled_start)} (${humanize(created.status)}).` } })
    }
  }

  return (
    <AreaGuard permission="appointment.manage">
      <form className="form-layout" onSubmit={onSubmit} noValidate>
        <ProblemAlert problem={problem} />
        <Card title="Book appointment" description="The HMS checks the clinician works in the department and the time is not in the past">
          <div className="form-grid">
            <div className="form-grid__wide"><PatientPicker value={patient} onChange={(p) => { setPatient(p); clearField('patient') }} error={errors.patient} /></div>
            <DepartmentSelect required value={form.department_id} onChange={(v) => { set('department_id')(v); set('staff_id')('') }} error={errors.department_id} />
            <StaffSelect label="Clinician" value={form.staff_id} onChange={set('staff_id')} departmentId={form.department_id || undefined}
              error={errors.staff_id} hint="Optional — staff of the selected department" />
            <Field label="Date and time" required error={errors.scheduled_start}>
              <Input type="datetime-local" value={form.scheduled_start} onChange={(e) => set('scheduled_start')(e.target.value)} />
            </Field>
            <Field label="Duration" error={errors.duration_minutes}>
              <Select value={form.duration_minutes} onChange={(e) => set('duration_minutes')(e.target.value)}>
                {[10, 15, 20, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </Select>
            </Field>
            <div className="form-grid__wide"><Field label="Reason" required error={errors.reason}><Input value={form.reason} onChange={(e) => set('reason')(e.target.value)} maxLength={500} /></Field></div>
            <div className="form-grid__wide"><Field label="Notes" error={errors.notes}><Textarea value={form.notes} onChange={(e) => set('notes')(e.target.value)} rows={2} /></Field></div>
          </div>
        </Card>
        <div className="form-actions">
          <LinkButton to="/workflows/appointments" variant="secondary">Cancel</LinkButton>
          <Button type="submit" variant="primary" loading={submitting} icon="checkCircle">Book appointment</Button>
        </div>
      </form>
    </AreaGuard>
  )
}

// ---------------------------------------------------------------- admissions

const ADMISSION_STATUSES = ['REQUESTED', 'APPROVED', 'ADMITTED', 'TRANSFERRED', 'DISCHARGED', 'CANCELLED']
const ADMISSION_ACTIONS: Record<AdmissionAction, DialogSpec<AdmissionAction>> = {
  approve: { action: 'approve', title: 'Approve admission', confirmLabel: 'Approve', description: 'You are recorded as the approving clinician.', body: () => ({}) },
  admit: { action: 'admit', title: 'Admit patient', confirmLabel: 'Admit', description: 'Opens the inpatient stay.',
    fields: [{ name: 'bed', label: 'Bed', kind: 'text' }, { name: 'attending_staff_id', label: 'Attending clinician', kind: 'staff' },
      { name: 'admitted_at', label: 'Admitted at', kind: 'datetime', hint: 'Leave empty for now' }],
    body: (v) => ({ bed: optionalText(v.bed), attending_staff_id: v.attending_staff_id || null, admitted_at: localInputToIso(v.admitted_at) }) },
  transfer: { action: 'transfer', title: 'Transfer patient', confirmLabel: 'Transfer', description: 'You are recorded as the transferring clinician.',
    fields: [{ name: 'to_department_id', label: 'To department', kind: 'department', required: true }, { name: 'to_bed', label: 'To bed', kind: 'text' }, REASON],
    body: (v) => ({ to_department_id: v.to_department_id, to_bed: optionalText(v.to_bed), reason: v.reason.trim() }) },
  discharge: { action: 'discharge', title: 'Discharge patient', confirmLabel: 'Discharge',
    fields: [{ name: 'disposition', label: 'Disposition', kind: 'select', required: true,
      options: ['HOME', 'REFERRED_OUT', 'AGAINST_MEDICAL_ADVICE', 'DECEASED', 'OTHER'].map((d) => ({ value: d, label: humanize(d) })) },
    { name: 'discharge_summary', label: 'Discharge summary', kind: 'textarea' }],
    body: (v) => ({ disposition: v.disposition, discharge_summary: optionalText(v.discharge_summary) }) },
  cancel: { action: 'cancel', title: 'Cancel admission', confirmLabel: 'Cancel', tone: 'danger', fields: [REASON], body: (v) => ({ reason: v.reason.trim() }) },
}
const ADMISSION_AVAILABLE: Record<string, AdmissionAction[]> = {
  REQUESTED: ['approve', 'cancel'], APPROVED: ['admit', 'cancel'], ADMITTED: ['transfer', 'discharge'], TRANSFERRED: ['transfer', 'discharge'],
}

export function AdmissionsPanel() {
  const { can } = useAuth()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [running, setRunning] = useState<{ spec: DialogSpec<AdmissionAction>; admission: Admission } | null>(null)
  const result = useQuery((s) => workflowApi.admissions({ status: status || undefined, limit: PAGE_SIZE, offset }, s), [status, offset])
  const manage = can('admission.manage')
  const columns: Column<Admission>[] = [
    { key: 'requested', header: 'Requested', numeric: true, width: 170, render: (a) => <span className="cell-strong">{formatDateTime(a.requested_at)}</span> },
    { key: 'patient', header: 'Patient', render: (a) => <PatientName id={a.patient_id} /> },
    { key: 'reason', header: 'Reason', render: (a) => <span className="cell-stack"><span>{a.reason}</span><span className="cell-sub">{humanize(a.admission_type)}</span>
      {a.cancellation_reason ? <span className="cell-sub">Cancelled: {a.cancellation_reason}</span> : null}</span> },
    { key: 'ward', header: 'Ward / bed', priority: 'secondary', render: (a) => <span className="cell-stack"><DepartmentName id={a.department_id} />
      {a.bed ? <span className="cell-sub">Bed {a.bed}</span> : null}</span> },
    { key: 'attending', header: 'Attending', priority: 'tertiary', render: (a) => (a.attending_staff_id ? <StaffName staffId={a.attending_staff_id} /> : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'Status', render: (a) => <StatusBadge status={a.status} size="sm" /> },
    ...(manage ? [{ key: 'actions', header: 'Actions', render: (a: Admission) => (
      <RowActions specs={ADMISSION_ACTIONS} available={ADMISSION_AVAILABLE[a.status] ?? []} onRun={(spec) => setRunning({ spec, admission: a })} />) }] : []),
  ]
  return (
    <AreaGuard permission="admission.view">
      <Notice />
      <div className="section-head">
        <div className="section-head__text"><h2 className="section-head__title">Admissions</h2></div>
        <div className="section-filters">
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All statuses</option>
              {ADMISSION_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </Field>
          {manage ? <LinkButton to="/workflows/admissions/new" variant="primary" icon="plus">Request admission</LinkButton> : null}
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Admissions" columns={columns} rows={result.data?.items} rowKey={(a) => a.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="bed" title={status ? 'No admissions with this status' : 'No admissions recorded'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="admissions" /> : null}
          </>
        )}
      </Card>
      {running ? (
        <ActionDialog key={`${running.admission.id}-${running.spec.action}`} open title={running.spec.title} confirmLabel={running.spec.confirmLabel}
          tone={running.spec.tone} description={running.spec.description} fields={running.spec.fields}
          onClose={() => setRunning(null)} onDone={result.reload}
          submit={(v) => workflowApi.admissionAction(running.admission.id, running.spec.action, running.spec.body?.(v))} />
      ) : null}
    </AreaGuard>
  )
}

export function RequestAdmissionPage() {
  const navigate = useNavigate()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [form, setForm] = useState({ department_id: '', admission_type: '', reason: '', bed: '', attending_staff_id: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!patient) missing.patient = 'Select the patient.'
    if (!form.department_id) missing.department_id = 'Select the ward or unit.'
    if (!form.admission_type) missing.admission_type = 'Select the admission type.'
    if (!form.reason.trim()) missing.reason = 'Enter the reason.'
    if (Object.keys(missing).length) return reject(missing, 'The admission has not been requested.')
    // requested_by is not sent: the backend records the signed-in user as the requester.
    const created = await run(() => workflowApi.requestAdmission(patient!.id, {
      department_id: form.department_id, admission_type: form.admission_type, reason: form.reason.trim(),
      bed: optionalText(form.bed), attending_staff_id: form.attending_staff_id || null,
    }))
    if (created) navigate('/workflows/admissions', { state: { notice: `Admission requested (${humanize(created.status)}).` } })
  }

  return (
    <AreaGuard permission="admission.manage">
      <form className="form-layout" onSubmit={onSubmit} noValidate>
        <ProblemAlert problem={problem} />
        <AuthorStatement verb="Requested" />
        <Card title="Request admission">
          <div className="form-grid">
            <div className="form-grid__wide"><PatientPicker value={patient} onChange={(p) => { setPatient(p); clearField('patient') }} error={errors.patient} /></div>
            <DepartmentSelect required label="Ward / unit" value={form.department_id} onChange={set('department_id')} error={errors.department_id} />
            <Field label="Admission type" required error={errors.admission_type}>
              <Select value={form.admission_type} onChange={(e) => set('admission_type')(e.target.value)}>
                <option value="">Select…</option>
                <option value="EMERGENCY">Emergency</option>
                <option value="ELECTIVE">Elective</option>
              </Select>
            </Field>
            <Field label="Bed" error={errors.bed} hint="Optional"><Input value={form.bed} onChange={(e) => set('bed')(e.target.value)} maxLength={30} /></Field>
            <StaffSelect label="Attending clinician" value={form.attending_staff_id} onChange={set('attending_staff_id')} error={errors.attending_staff_id} hint="Optional" />
            <div className="form-grid__wide"><Field label="Reason" required error={errors.reason}><Input value={form.reason} onChange={(e) => set('reason')(e.target.value)} maxLength={500} /></Field></div>
          </div>
        </Card>
        <div className="form-actions">
          <LinkButton to="/workflows/admissions" variant="secondary">Cancel</LinkButton>
          <Button type="submit" variant="primary" loading={submitting} icon="checkCircle">Request admission</Button>
        </div>
      </form>
    </AreaGuard>
  )
}

// ---------------------------------------------------------------- tasks

const TASK_STATUSES = ['OPEN', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
const TASK_TYPES = ['SAMPLE_COLLECTION', 'MEDICATION_ADMINISTRATION', 'NURSING_CARE', 'PATIENT_TRANSPORT', 'DISCHARGE_PREPARATION', 'FOLLOW_UP', 'ADMINISTRATIVE', 'OTHER']
const TASK_ACTIONS: Record<TaskAction, DialogSpec<TaskAction>> = {
  assign: { action: 'assign', title: 'Assign task', confirmLabel: 'Assign',
    fields: [{ name: 'staff_id', label: 'Assign to', kind: 'staff', required: true }], body: (v) => ({ staff_id: v.staff_id }) },
  start: { action: 'start', title: 'Start task', confirmLabel: 'Start' },
  complete: { action: 'complete', title: 'Complete task', confirmLabel: 'Complete',
    fields: [{ name: 'completion_notes', label: 'Completion notes', kind: 'textarea' }], body: (v) => ({ completion_notes: optionalText(v.completion_notes) }) },
  cancel: { action: 'cancel', title: 'Cancel task', confirmLabel: 'Cancel', tone: 'danger', fields: [REASON], body: (v) => ({ reason: v.reason.trim() }) },
}

export function TasksPanel() {
  const { can, hasAllScope, user } = useAuth()
  const [status, setStatus] = useState('')
  const [mine, setMine] = useState(false)
  const [offset, setOffset] = useState(0)
  const [running, setRunning] = useState<{ spec: DialogSpec<TaskAction>; task: WorkflowTask } | null>(null)
  const allScope = hasAllScope('workflow.view')
  const result = useQuery((s) => workflowApi.tasks({ status: status || undefined, assigned_staff_id: mine ? user?.staff.id : undefined,
    limit: PAGE_SIZE, offset }, s), [status, mine, offset])
  const manage = can('workflow.manage')
  const manageAll = hasAllScope('workflow.manage')
  const available = (t: WorkflowTask): TaskAction[] => {
    const own = t.assigned_staff_id === user?.staff.id
    if (!manage || (!manageAll && !own)) return []
    switch (t.status) {
      case 'OPEN': return manageAll ? ['assign', 'cancel'] : ['cancel']
      case 'ASSIGNED': return ['start', 'cancel']
      case 'IN_PROGRESS': return ['complete', 'cancel']
      default: return []
    }
  }
  const columns: Column<WorkflowTask>[] = [
    { key: 'title', header: 'Task', render: (t) => <span className="cell-stack"><span className="cell-strong">{t.title}</span>
      <span className="cell-sub">{humanize(t.workflow_type)}{t.due_at ? ` · due ${formatDateTime(t.due_at)}` : ''}</span></span> },
    { key: 'patient', header: 'Patient', priority: 'secondary', render: (t) => <PatientName id={t.patient_id} /> },
    { key: 'priority', header: 'Priority', render: (t) => <StatusBadge status={t.priority} size="sm" /> },
    { key: 'assignee', header: 'Assigned to', render: (t) => (t.assigned_staff_id ? <StaffName staffId={t.assigned_staff_id} /> : <span className="text-subtle">Unassigned</span>) },
    { key: 'status', header: 'Status', render: (t) => <span className="cell-stack"><StatusBadge status={t.status} size="sm" />
      {t.completion_notes ? <span className="cell-sub">{t.completion_notes}</span> : null}
      {t.cancellation_reason ? <span className="cell-sub">Cancelled: {t.cancellation_reason}</span> : null}</span> },
    ...(manage ? [{ key: 'actions', header: 'Actions', render: (t: WorkflowTask) => (
      <RowActions specs={TASK_ACTIONS} available={available(t)} onRun={(spec) => setRunning({ spec, task: t })} />) }] : []),
  ]
  return (
    <AreaGuard permission="workflow.view">
      <Notice />
      <div className="section-head">
        <div className="section-head__text">
          <h2 className="section-head__title">Tasks</h2>
          {!allScope ? <div className="section-head__meta"><span>Showing the tasks assigned to you (your workflow access is limited to your own tasks)</span></div> : null}
        </div>
        <div className="section-filters">
          {allScope ? (
            <Field label="Assigned">
              <Select value={mine ? 'me' : ''} onChange={(e) => { setMine(e.target.value === 'me'); setOffset(0) }}>
                <option value="">Everyone</option>
                <option value="me">Assigned to me</option>
              </Select>
            </Field>
          ) : null}
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All statuses</option>
              {TASK_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </Field>
          {manageAll ? <LinkButton to="/workflows/tasks/new" variant="primary" icon="plus">New task</LinkButton> : null}
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Tasks" columns={columns} rows={result.data?.items} rowKey={(t) => t.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="workflows" title={status || mine ? 'No tasks match these filters' : 'No tasks'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="tasks" /> : null}
          </>
        )}
      </Card>
      {running ? (
        <ActionDialog key={`${running.task.id}-${running.spec.action}`} open title={running.spec.title} confirmLabel={running.spec.confirmLabel}
          tone={running.spec.tone} description={running.spec.description} fields={running.spec.fields}
          onClose={() => setRunning(null)} onDone={result.reload}
          submit={(v) => workflowApi.taskAction(running.task.id, running.spec.action, running.spec.body?.(v))} />
      ) : null}
    </AreaGuard>
  )
}

export function NewTaskPage() {
  const navigate = useNavigate()
  const { hasAllScope } = useAuth()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [form, setForm] = useState({ workflow_type: '', title: '', description: '', priority: 'NORMAL', department_id: '', due_at: '', assigned_staff_id: '' })
  const { submitting, problem, errors, run, reject, clearField } = useSubmit()
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); clearField(field) }

  if (!hasAllScope('workflow.manage')) {
    return <Card><EmptyState icon="lock" title="Not available for your role"
      description="Creating tasks requires the workflow.manage permission for all tasks (your access is limited to your own tasks)." /></Card>
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!form.workflow_type) missing.workflow_type = 'Select the task type.'
    if (!form.title.trim()) missing.title = 'Enter the title.'
    if (Object.keys(missing).length) return reject(missing, 'The task has not been created.')
    // created_by is not sent: the backend records the signed-in user as the creator.
    const created = await run(() => workflowApi.createTask({
      workflow_type: form.workflow_type, title: form.title.trim(), description: optionalText(form.description), priority: form.priority,
      patient_id: patient?.id ?? null, department_id: form.department_id || null, due_at: localInputToIso(form.due_at),
      assigned_staff_id: form.assigned_staff_id || null,
    }))
    if (created) navigate('/workflows/tasks', { state: { notice: `Task “${created.title}” created (${humanize(created.status)}).` } })
  }

  return (
    <form className="form-layout" onSubmit={onSubmit} noValidate>
      <ProblemAlert problem={problem} />
      <AuthorStatement verb="Created" />
      <Card title="New task">
        <div className="form-grid">
          <Field label="Type" required error={errors.workflow_type}>
            <Select value={form.workflow_type} onChange={(e) => set('workflow_type')(e.target.value)}>
              <option value="">Select…</option>
              {TASK_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </Select>
          </Field>
          <Field label="Priority" error={errors.priority}>
            <Select value={form.priority} onChange={(e) => set('priority')(e.target.value)}>
              {['LOW', 'NORMAL', 'HIGH', 'URGENT'].map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
            </Select>
          </Field>
          <div className="form-grid__wide"><Field label="Title" required error={errors.title}><Input value={form.title} onChange={(e) => set('title')(e.target.value)} maxLength={200} /></Field></div>
          <div className="form-grid__wide"><Field label="Description" error={errors.description}><Textarea value={form.description} onChange={(e) => set('description')(e.target.value)} rows={3} /></Field></div>
          <div className="form-grid__wide"><PatientPicker value={patient} onChange={setPatient} error={errors.patient_id} /></div>
          <DepartmentSelect value={form.department_id} onChange={set('department_id')} error={errors.department_id} />
          <Field label="Due" error={errors.due_at}><Input type="datetime-local" value={form.due_at} onChange={(e) => set('due_at')(e.target.value)} /></Field>
          <StaffSelect label="Assign to" value={form.assigned_staff_id} onChange={set('assigned_staff_id')} error={errors.assigned_staff_id} hint="Optional — assigns immediately" />
        </div>
      </Card>
      <div className="form-actions">
        <LinkButton to="/workflows/tasks" variant="secondary">Cancel</LinkButton>
        <Button type="submit" variant="primary" loading={submitting} icon="checkCircle">Create task</Button>
      </div>
    </form>
  )
}
