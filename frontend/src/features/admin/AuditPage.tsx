/**
 * Audit trail (GET /api/audit-events, /api/audit-events/{id}; audit.view). Read-only: the HMS has no audit write API.
 * Shown exactly as recorded — the backend never stores clinical text, secrets or query strings in audit metadata.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { accessApi, auditApi } from '../../api/endpoints'
import type { AuditQuery } from '../../api/endpoints'
import type { AuditEventDetail } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { Column } from '../../components/ui'
import {
  Button, Card, DataTable, Drawer, EmptyState, ErrorState, Field, Input, LoadingState, Pagination, Select, StatusBadge,
} from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { describeAuditAction } from '../../lib/audit'
import { formatDateTime } from '../../lib/format'
import { localInputToIso } from '../../lib/forms'
import { Link } from 'react-router-dom'
import { AdminGuard, AuditTag } from './accessUi'

const PAGE_SIZE = 25
const EMPTY = { action: '', outcome: '', actor_user_id: '', resource_type: '', patient_id: '', occurred_from: '', occurred_to: '' }
type Filters = typeof EMPTY

function toQuery(f: Filters): AuditQuery {
  return {
    action: f.action.trim() || undefined, outcome: f.outcome || undefined, actor_user_id: f.actor_user_id || undefined,
    resource_type: f.resource_type.trim() || undefined, patient_id: f.patient_id.trim() || undefined,
    occurred_from: localInputToIso(f.occurred_from) ?? undefined, occurred_to: localInputToIso(f.occurred_to) ?? undefined,
  }
}

export function AuditPage() {
  const { can } = useAuth()
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [applied, setApplied] = useState<Filters>(EMPTY)
  const [offset, setOffset] = useState(0)
  const [openId, setOpenId] = useState<string | null>(null)
  const query = toQuery(applied)
  const result = useQuery((s) => auditApi.search({ ...query, limit: PAGE_SIZE, offset }, s), [JSON.stringify(query), offset])
  const users = useQuery((s) => accessApi.users({ limit: 100 }, s), [], { enabled: can('user.view') })
  const set = (field: keyof Filters) => (value: string) => setDraft((d) => ({ ...d, [field]: value }))
  const apply = (event: FormEvent) => { event.preventDefault(); setApplied(draft); setOffset(0) }
  const reset = () => { setDraft(EMPTY); setApplied(EMPTY); setOffset(0) }
  const filtered = JSON.stringify(applied) !== JSON.stringify(EMPTY)

  const columns: Column<AuditEventDetail>[] = [
    { key: 'time', header: 'Time', numeric: true, width: 180, render: (e) => <span className="cell-strong">{formatDateTime(e.occurred_at)}</span> },
    { key: 'action', header: 'Action', render: (e) => <span className="cell-stack"><span>{describeAuditAction(e.action)}</span>
      <span className="cell-sub mono">{e.action}</span></span> },
    { key: 'outcome', header: 'Outcome', render: (e) => <StatusBadge status={e.outcome} size="sm" /> },
    { key: 'actor', header: 'Actor', render: (e) => (e.actor_username ? <span className="mono">{e.actor_username}</span> : <span className="text-subtle">Unauthenticated</span>) },
    { key: 'resource', header: 'Resource', priority: 'secondary', render: (e) => (e.resource_type
      ? <span className="cell-stack"><span>{e.resource_type}</span>{e.resource_id ? <span className="cell-sub mono">{e.resource_id.slice(0, 8)}…</span> : null}</span>
      : <span className="text-subtle">—</span>) },
    // A reference only: resolving names here would itself read (and audit) patient records for every row.
    { key: 'patient', header: 'Patient', priority: 'tertiary', render: (e) => (e.patient_id && can('patient.view')
      ? <Link to={`/patients/${e.patient_id}`} onClick={(ev) => ev.stopPropagation()} className="mono">{e.patient_id.slice(0, 8)}…</Link>
      : e.patient_id ? <span className="mono text-muted">{e.patient_id.slice(0, 8)}…</span> : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'HTTP', numeric: true, priority: 'secondary', render: (e) => e.status_code ?? <span className="text-subtle">—</span> },
  ]

  return (
    <AdminGuard anyOf={['audit.view']}>
      <div className="admin-head">
        <div className="admin-head__title"><h2>Audit trail</h2><AuditTag /></div>
      </div>
      <Card>
        <form className="audit-filters" onSubmit={apply}>
          <Field label="Outcome">
            <Select value={draft.outcome} onChange={(e) => set('outcome')(e.target.value)}>
              <option value="">All outcomes</option>
              <option value="SUCCESS">Success</option>
              <option value="FAILURE">Failure</option>
              <option value="DENIED">Denied</option>
            </Select>
          </Field>
          {can('user.view') ? (
            <Field label="Actor">
              <Select value={draft.actor_user_id} onChange={(e) => set('actor_user_id')(e.target.value)}>
                <option value="">Anyone</option>
                {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
              </Select>
            </Field>
          ) : null}
          <Field label="Action" hint="Exact, e.g. auth.login or POST /api/patients">
            <Input value={draft.action} onChange={(e) => set('action')(e.target.value)} />
          </Field>
          <Field label="Resource type" hint="e.g. users, roles, encounters">
            <Input value={draft.resource_type} onChange={(e) => set('resource_type')(e.target.value)} />
          </Field>
          <Field label="From"><Input type="datetime-local" value={draft.occurred_from} onChange={(e) => set('occurred_from')(e.target.value)} /></Field>
          <Field label="To"><Input type="datetime-local" value={draft.occurred_to} onChange={(e) => set('occurred_to')(e.target.value)} /></Field>
          <Field label="Patient reference" hint="Patient record id (UUID)">
            <Input value={draft.patient_id} onChange={(e) => set('patient_id')(e.target.value)} />
          </Field>
          <div className="audit-filters__actions">
            <Button variant="secondary" onClick={reset} disabled={!filtered}>Clear</Button>
            <Button type="submit" variant="primary" icon="filter">Apply filters</Button>
          </div>
        </form>
      </Card>
      <div style={{ height: 'var(--space-4)' }} />
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Audit events" columns={columns} rows={result.data?.items} rowKey={(e) => e.id}
              loading={result.loading && !result.data} onRowClick={(e) => setOpenId(e.id)}
              rowLabel={(e) => `Open audit event ${e.action} at ${formatDateTime(e.occurred_at)}`}
              empty={<EmptyState icon="document" title={filtered ? 'No audit events match these filters' : 'No audit events'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="events" /> : null}
          </>
        )}
      </Card>
      <Drawer open={Boolean(openId)} onClose={() => setOpenId(null)} title="Audit event" size="lg"
        description={<AuditTag />}>
        {openId ? <AuditEventView id={openId} /> : null}
      </Drawer>
    </AdminGuard>
  )
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function AuditEventView({ id }: { id: string }) {
  const event = useQuery((s) => auditApi.get(id, s), [id])
  if (event.error) return <ErrorState error={event.error} onRetry={event.reload} />
  if (!event.data) return <LoadingState label="Loading audit event…" />
  const e = event.data
  const rows: Array<[string, unknown]> = [
    ['Occurred', formatDateTime(e.occurred_at)], ['Action', `${describeAuditAction(e.action)} (${e.action})`], ['Outcome', e.outcome],
    ['HTTP', e.http_method ? `${e.http_method} ${e.status_code ?? ''}` : e.status_code], ['Route', e.route],
    ['Actor', e.actor_username], ['Actor user id', e.actor_user_id], ['Actor staff id', e.actor_staff_id], ['Session id', e.session_id],
    ['Resource type', e.resource_type], ['Resource id', e.resource_id], ['Patient id', e.patient_id],
    ['Client IP', e.client_ip], ['User agent', e.user_agent], ['Request id', e.request_id], ['Event id', e.id],
  ]
  const details = Object.entries(e.details ?? {})
  return (
    <div className="stack">
      <dl className="kv">
        {rows.map(([k, v]) => <div key={k} style={{ display: 'contents' }}><dt>{k}</dt><dd className={/id$|IP|Route/.test(k) ? 'mono' : ''}>{display(v)}</dd></div>)}
      </dl>
      <Card title="Details" description="Structured metadata recorded with the event (never clinical text or secrets)">
        {details.length ? (
          <dl className="kv">
            {details.map(([k, v]) => <div key={k} style={{ display: 'contents' }}><dt className="mono">{k}</dt><dd className="mono">{display(v)}</dd></div>)}
          </dl>
        ) : <p className="text-muted">No additional details.</p>}
      </Card>
    </div>
  )
}
