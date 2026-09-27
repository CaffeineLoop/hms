/**
 * Dashboard shell (UI-0). Every figure and list comes from the existing HMS APIs, requested only when the
 * signed-in user holds the relevant permission. Nothing is estimated, sampled or invented; metrics the user
 * cannot see are shown as "not available for your role".
 */
import { useNavigate } from 'react-router-dom'
import { aiApi, auditApi, patientsApi, workflowApi } from '../api/endpoints'
import type { AuditEvent, Patient, WorkflowTask } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { Icon } from '../components/icons/Icon'
import type { IconName } from '../components/icons/Icon'
import {
  Avatar, Badge, Card, DataTable, EmptyState, ErrorState, LinkButton, LoadingState, PageHeader, ProvenanceTag,
  StatCard, StatusBadge,
} from '../components/ui'
import type { Column } from '../components/ui'
import { useQuery } from '../hooks/useQuery'
import { describeAuditAction } from '../lib/audit'
import {
  ageFromDob, formatLongDate, formatRelative, formatShortDateTime, greeting, humanize, patientDisplayName, sexLabel,
} from '../lib/format'
import './DashboardPage.css'

const NO_ACCESS = 'Not available for your role'

function startOfToday(): Date {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d
}

export function DashboardPage() {
  const { user, can, canAny } = useAuth()
  const navigate = useNavigate()
  const canPatients = can('patient.view')
  const canTasks = can('workflow.view')
  const canAdmissions = can('admission.view')
  const canAppointments = can('appointment.view')
  const canAi = canAny('ai.analysis', 'ai.review')
  const canAudit = can('audit.view')

  const patients = useQuery((s) => patientsApi.list({ limit: 6 }, s), [], { enabled: canPatients })
  const activeTasks = useQuery(async (s) => {
    const [open, assigned, inProgress] = await Promise.all(
      ['OPEN', 'ASSIGNED', 'IN_PROGRESS'].map((status) => workflowApi.tasks({ status, limit: 8 }, s)))
    const items = [...inProgress.items, ...assigned.items, ...open.items].slice(0, 8)
    return { total: open.total + assigned.total + inProgress.total, open: open.total, inProgress: inProgress.total, items }
  }, [], { enabled: canTasks })
  const inpatients = useQuery((s) => workflowApi.admissions({ status: 'ADMITTED', limit: 1 }, s), [], { enabled: canAdmissions })
  const appointments = useQuery((s) => {
    const from = startOfToday()
    const to = new Date(from.getTime() + 86_400_000)
    return workflowApi.appointments({ scheduled_from: from.toISOString(), scheduled_to: to.toISOString(), limit: 1 }, s)
  }, [], { enabled: canAppointments })
  const urgentOpen = useQuery((s) => workflowApi.tasks({ priority: 'URGENT', status: 'OPEN', limit: 1 }, s), [],
    { enabled: canTasks })
  const aiPending = useQuery((s) => aiApi.riskAnalyses({ review_status: 'PENDING_REVIEW', limit: 1 }, s), [], { enabled: canAi })
  const activity = useQuery((s) => auditApi.events({ limit: 8 }, s), [], { enabled: canAudit })

  const firstName = user?.staff.full_name.split(' ')[0] ?? ''

  const taskColumns: Column<WorkflowTask>[] = [
    { key: 'title', header: 'Task', width: '38%', render: (t) => <span className="dash-task__title">{t.title}</span> },
    { key: 'type', header: 'Type', priority: 'secondary', render: (t) => <span className="text-muted">{humanize(t.workflow_type)}</span> },
    { key: 'priority', header: 'Priority', render: (t) => <StatusBadge status={t.priority} size="sm" /> },
    { key: 'status', header: 'Status', render: (t) => <StatusBadge status={t.status} size="sm" /> },
    { key: 'due', header: 'Due', priority: 'tertiary', numeric: true,
      render: (t) => (t.due_at ? <span className="nowrap">{formatShortDateTime(t.due_at)}</span> : <span className="text-subtle">—</span>) },
  ]

  return (
    <>
      <PageHeader
        title={`${greeting()}, ${firstName}`}
        description={`${formatLongDate(new Date())} · ${user ? humanize(user.staff.designation) : ''}`}
        actions={can('patient.create') ? <LinkButton to="/patients/new" variant="primary" icon="plus">Register patient</LinkButton> : null}
      />

      <section className="dash-stats" aria-label="Key figures">
        <StatCard label="Patients" icon="patients" to="/patients" loading={patients.loading}
          value={patients.data?.total} hint="Registered records"
          unavailable={!canPatients ? NO_ACCESS : patients.error ? 'Could not load' : null} />
        <StatCard label="Active tasks" icon="workflows" to="/workflows/tasks" loading={activeTasks.loading}
          value={activeTasks.data?.total}
          hint={activeTasks.data ? `${activeTasks.data.open} open · ${activeTasks.data.inProgress} in progress` : undefined}
          unavailable={!canTasks ? NO_ACCESS : activeTasks.error ? 'Could not load' : null} />
        <StatCard label="Inpatients" icon="bed" to="/workflows/admissions" loading={inpatients.loading}
          value={inpatients.data?.total} hint="Currently admitted"
          unavailable={!canAdmissions ? NO_ACCESS : inpatients.error ? 'Could not load' : null} />
        <StatCard label="Appointments" icon="calendar" to="/workflows/appointments" loading={appointments.loading}
          value={appointments.data?.total} hint="Scheduled today"
          unavailable={!canAppointments ? NO_ACCESS : appointments.error ? 'Could not load' : null} />
        <StatCard label="AI reviews" icon="ai" tone="ai" to="/ai" loading={aiPending.loading}
          value={aiPending.data?.total} hint="Pending clinician review"
          unavailable={!canAi ? NO_ACCESS : aiPending.error ? 'Could not load' : null} />
      </section>

      <div className="grid-12 dash-grid">
        <Card className="span-7" title="Pending tasks" description="Open, assigned and in-progress workflow tasks"
          padding="none" actions={canTasks ? <LinkButton to="/workflows/tasks" variant="ghost" size="sm" iconRight="arrowRight">View all</LinkButton> : null}>
          {!canTasks ? <EmptyState compact icon="lock" title={NO_ACCESS} description="Workflow tasks require the workflow.view permission." />
            : activeTasks.error ? <ErrorState compact error={activeTasks.error} onRetry={activeTasks.reload} />
              : (
                <DataTable caption="Pending workflow tasks" columns={taskColumns} rows={activeTasks.data?.items}
                  rowKey={(t) => t.id} loading={activeTasks.loading} density="compact"
                  empty={<EmptyState compact icon="checkCircle" title="No pending tasks" description="Nothing is waiting for action." />} />
              )}
        </Card>


        <div className="span-5 stack dash-side">
          <Card title="Alerts" description="Items that may need attention">
            <AlertsPanel canAi={canAi} aiPending={aiPending.data?.total} canTasks={canTasks}
              urgentOpen={urgentOpen.data?.total} />
          </Card>
          <Card title="Reading clinical information" description="How the HMS marks where information comes from">
            <ul className="dash-legend">
              <li><ProvenanceTag kind="record" /><span>Entered and attributed to a clinician.</span></li>
              <li><ProvenanceTag kind="system" /><span>Workflow or process status maintained by the HMS.</span></li>
              <li><ProvenanceTag kind="ai" /><span>Generated for review only — never a diagnosis or order.</span></li>
            </ul>
          </Card>
        </div>

        <Card className="span-5" title="Recent patient registrations" padding="none"
          actions={canPatients ? <LinkButton to="/patients" variant="ghost" size="sm" iconRight="arrowRight">All patients</LinkButton> : null}>
          {!canPatients ? <EmptyState compact icon="lock" title={NO_ACCESS} />
            : patients.error ? <ErrorState compact error={patients.error} onRetry={patients.reload} />
              : patients.loading ? <LoadingState rows={5} label="Loading patients" />
                : patients.data && patients.data.items.length > 0 ? (
                  <ul className="dash-patients">
                    {patients.data.items.map((p) => <PatientRow key={p.id} patient={p} onOpen={() => navigate(`/patients/${p.id}`)} />)}
                  </ul>
                ) : <EmptyState compact icon="patients" title="No patients registered yet" />}
        </Card>

        <Card className="span-7" title="Recent activity" description="From the HMS audit trail" padding="none">
          {!canAudit ? (
            <EmptyState compact icon="lock" title={NO_ACCESS} description="The activity feed is drawn from the audit trail (audit.view)." />
          ) : activity.error ? <ErrorState compact error={activity.error} onRetry={activity.reload} />
            : activity.loading ? <LoadingState rows={6} label="Loading activity" />
              : activity.data && activity.data.items.length > 0 ? (
                <ol className="dash-activity">{activity.data.items.map((e) => <ActivityRow key={e.id} event={e} />)}</ol>
              ) : <EmptyState compact title="No recorded activity" />}
        </Card>

        <Card className="span-12" title="Quick actions" description="Shortcuts to common tasks (modules arrive in upcoming UI stages)">
          <QuickActions />
        </Card>

      </div>
    </>
  )
}

function PatientRow({ patient, onOpen }: { patient: Patient; onOpen: () => void }) {
  const name = patientDisplayName(patient)
  return (
    <li>
      <button type="button" className="dash-patient" onClick={onOpen}>
        <Avatar name={`${patient.first_name} ${patient.last_name}`} size={34} tone="neutral" />
        <span className="dash-patient__id">
          <span className="dash-patient__name">{name}</span>
          <span className="dash-patient__meta">
            <span className="mono">{patient.patient_number}</span>
            <span aria-hidden="true">·</span>
            <span className="tabular">{ageFromDob(patient.date_of_birth)} y</span>
            <span aria-hidden="true">·</span>
            {sexLabel(patient.sex)}
          </span>
        </span>
        <span className="dash-patient__time">{formatRelative(patient.created_at)}</span>
      </button>
    </li>
  )
}

function ActivityRow({ event }: { event: AuditEvent }) {
  return (
    <li className="dash-activity__item">
      <span className={`dash-activity__marker dash-activity__marker--${event.outcome.toLowerCase()}`} aria-hidden="true" />
      <div className="dash-activity__body">
        <p className="dash-activity__text">
          <strong>{event.actor_username ?? 'Unknown user'}</strong> · {describeAuditAction(event.action)}
        </p>
        <p className="dash-activity__meta">{formatRelative(event.occurred_at)}</p>
      </div>
      {event.outcome !== 'SUCCESS' ? <StatusBadge status={event.outcome} size="sm" /> : null}
    </li>
  )
}

function AlertsPanel({ canAi, aiPending, canTasks, urgentOpen }: { canAi: boolean; aiPending?: number; canTasks: boolean; urgentOpen?: number }) {
  const items: Array<{ key: string; icon: IconName; tone: 'ai' | 'warning' | 'info'; title: string; detail: string }> = []
  if (canAi && aiPending) {
    items.push({ key: 'ai', icon: 'ai', tone: 'ai', title: `${aiPending} AI suggestion${aiPending === 1 ? '' : 's'} awaiting review`,
      detail: 'Potential risk signals for the next four days. Suggestions only — clinician review required.' })
  }
  if (canTasks && urgentOpen) {
    items.push({ key: 'urgent', icon: 'alert', tone: 'warning', title: `${urgentOpen} urgent open task${urgentOpen === 1 ? '' : 's'}`,
      detail: 'Urgent workflow tasks that have not yet been assigned.' })
  }
  if (items.length === 0) {
    return <EmptyState compact icon="checkCircle" title="No active alerts" description="Nothing currently needs your attention." />
  }
  return (
    <ul className="dash-alerts">
      {items.map((a) => (
        <li key={a.key} className={`dash-alert dash-alert--${a.tone}`}>
          <span className="dash-alert__icon"><Icon name={a.icon} size={16} /></span>
          <div>
            <p className="dash-alert__title">{a.title}</p>
            <p className="dash-alert__detail">{a.detail}</p>
            {a.tone === 'ai' ? <div className="dash-alert__tag"><ProvenanceTag kind="ai" /></div> : null}
          </div>
        </li>
      ))}
    </ul>
  )
}

function QuickActions() {
  const { can, canAny, hasAllScope, canReadClinical } = useAuth()
  // Every shortcut opens a working screen; lab ordering and prescribing are not part of the UI, so they are not offered.
  const actions: Array<{ label: string; detail: string; icon: IconName; to: string; show: boolean; live?: boolean }> = [
    { label: 'Register a patient', detail: 'New patient record', icon: 'patients', to: '/patients/new', show: can('patient.create'), live: true },
    { label: 'Record vital signs', detail: 'Choose the patient, then record', icon: 'pulse', to: '/clinical?next=vitals/new',
      show: hasAllScope('observation.create') && canReadClinical('observation.view'), live: true },
    { label: 'Book an appointment', detail: 'Workflows', icon: 'calendar', to: '/workflows/appointments/new', show: can('appointment.manage'), live: true },
    { label: 'Review diagnostics', detail: 'Lab orders, results and reports', icon: 'diagnostics', to: '/diagnostics',
      show: canReadClinical('lab.view') || canReadClinical('report.view'), live: true },
    { label: 'Review prescriptions', detail: 'Read-only', icon: 'prescriptions', to: '/prescriptions', show: canReadClinical('prescription.view'), live: true },
    { label: 'Review AI suggestions', detail: 'Clinician review queue', icon: 'ai', to: '/ai', show: canAny('ai.review', 'ai.analysis'), live: true },
    { label: 'View the audit trail', detail: 'Administration', icon: 'shieldCheck', to: '/administration/audit', show: can('audit.view'), live: true },
  ]
  const visible = actions.filter((a) => a.show)
  if (visible.length === 0) return <EmptyState compact title="No quick actions for your role" />
  return (
    <ul className="dash-actions">
      {visible.map((a) => (
        <li key={a.label}>
          <LinkButton to={a.to} variant="secondary" block icon={a.icon}>{a.label}</LinkButton>
          <span className="dash-actions__detail">{a.detail}{a.live ? null : <Badge size="sm" variant="outline">Soon</Badge>}</span>
        </li>
      ))}
    </ul>
  )
}
