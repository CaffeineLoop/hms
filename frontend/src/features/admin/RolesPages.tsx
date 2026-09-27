/**
 * Roles and the permission catalog (GET/POST/PATCH /api/roles..., /api/permissions). Grants are Role → Permission +
 * Scope (ALL | OWN). Role reads need role.manage or permission.manage; role edits need role.manage; grants need
 * permission.manage. The backend refuses: editing the system role, changing a role you hold, granting what you do
 * not hold yourself — its answer is shown as is.
 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { accessApi } from '../../api/endpoints'
import type { Grant, Role } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { Column } from '../../components/ui'
import {
  Alert, Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, ErrorState, Field, LinkButton, LoadingState, Pagination,
  Select, StatusBadge,
} from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { useSubmit } from '../../hooks/useSubmit'
import { permissionDomain } from '../../lib/access'
import { formatDateTime } from '../../lib/format'
import { ActionDialog, ProblemAlert } from '../writes/WriteControls'
import { AdminGuard, ConfigTag, RoleLink, ScopeBadge } from './accessUi'

const ROLE_READERS = ['role.manage', 'permission.manage']
const PAGE_SIZE = 25

export function RolesPage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)
  const result = useQuery((s) => accessApi.roles({ status: status || undefined, limit: PAGE_SIZE, offset }, s), [status, offset])
  const columns: Column<Role>[] = [
    { key: 'name', header: 'Role', render: (r) => <span className="cell-stack"><span className="cell-strong">{r.name}</span>
      {r.description ? <span className="cell-sub">{r.description}</span> : null}</span> },
    { key: 'kind', header: 'Type', render: (r) => (r.is_superuser ? <Badge tone="danger" size="sm">System · all permissions</Badge> : <Badge size="sm">Custom grants</Badge>) },
    { key: 'grants', header: 'Permissions', numeric: true, render: (r) => (r.is_superuser ? 'All' : `${r.permissions.length} (${r.permissions.filter((p) => p.scope === 'OWN').length} OWN)`) },
    { key: 'users', header: 'Users', numeric: true, render: (r) => r.user_count },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} size="sm" /> },
  ]
  return (
    <AdminGuard anyOf={ROLE_READERS}>
      <div className="admin-head">
        <div className="admin-head__title"><h2>Roles</h2><ConfigTag /></div>
        <div className="section-filters">
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All statuses</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </Select>
          </Field>
          {can('role.manage') ? <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>New role</Button> : null}
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Roles" columns={columns} rows={result.data?.items} rowKey={(r) => r.id} loading={result.loading && !result.data}
              onRowClick={(r) => navigate(`/administration/roles/${r.id}`)} rowLabel={(r) => `Open role ${r.name}`}
              empty={<EmptyState icon="shieldCheck" title="No roles" />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="roles" /> : null}
          </>
        )}
      </Card>
      {creating ? (
        <ActionDialog open title="New role" confirmLabel="Create role" onClose={() => setCreating(false)} onDone={() => undefined}
          description="Role names are upper case (letters, digits, underscores). Add permissions on the role page."
          fields={[{ name: 'name', label: 'Name', kind: 'text', required: true, hint: 'e.g. WARD_CLERK' },
            { name: 'description', label: 'Description', kind: 'textarea' }]}
          submit={async (v) => {
            const role = await accessApi.createRole({ name: v.name.trim(), description: v.description.trim() || null })
            navigate(`/administration/roles/${role.id}`)
          }} />
      ) : null}
    </AdminGuard>
  )
}

export function RoleDetailPage() {
  const { roleId = '' } = useParams()
  const { user: me, can } = useAuth()
  const role = useQuery((s) => accessApi.role(roleId, s), [roleId])
  const catalog = useQuery((s) => accessApi.permissions(s), [])
  const [dialog, setDialog] = useState<null | 'edit' | 'deactivate' | 'reactivate' | { revoke: Grant } | { rescope: Grant }>(null)
  const [grantCode, setGrantCode] = useState('')
  const [grantScope, setGrantScope] = useState<'ALL' | 'OWN'>('ALL')
  const action = useSubmit()
  const back = <LinkButton to="/administration/roles" variant="ghost" size="sm" icon="chevronLeft">All roles</LinkButton>

  if (role.error) return <AdminGuard anyOf={ROLE_READERS}><Card>{back}<ErrorState error={role.error} /></Card></AdminGuard>
  if (!role.data) return <AdminGuard anyOf={ROLE_READERS}><LoadingState label="Loading role…" /></AdminGuard>
  const r = role.data
  const describe = new Map((catalog.data ?? []).map((p) => [p.code, p.description]))
  const held = Boolean(me?.roles.includes(r.name))
  const editRole = can('role.manage') && !r.is_superuser
  const editGrants = can('permission.manage') && !r.is_superuser
  const ungranted = (catalog.data ?? []).filter((p) => !r.permissions.some((g) => g.code === p.code))
  const domains = [...new Set(r.permissions.map((g) => permissionDomain(g.code)))].sort()

  async function mutate(write: () => Promise<unknown>) {
    const ok = await action.run(async () => { await write(); return true })
    setDialog(null)
    if (ok) role.reload()
    return ok
  }

  return (
    <AdminGuard anyOf={ROLE_READERS}>
      <div className="stack">
        <div>{back}</div>
        <div className="admin-head">
          <div className="admin-head__title"><h2>{r.name}</h2><StatusBadge status={r.status} size="sm" />
            {r.is_superuser ? <Badge tone="danger" size="sm">System role</Badge> : null}<ConfigTag /></div>
          {editRole ? (
            <div className="action-bar">
              <Button size="sm" icon="edit" onClick={() => setDialog('edit')}>Edit details</Button>
              {r.status === 'ACTIVE'
                ? <Button size="sm" variant="danger-ghost" onClick={() => setDialog('deactivate')}>Deactivate role</Button>
                : <Button size="sm" variant="primary" onClick={() => setDialog('reactivate')}>Reactivate role</Button>}
            </div>
          ) : null}
        </div>
        {r.description ? <p className="text-muted">{r.description}</p> : null}
        {held && !r.is_superuser ? <Alert tone="info" title="You hold this role">The HMS does not let you change the permissions of a role you hold.</Alert> : null}
        <ProblemAlert problem={action.problem} />
        <p className="text-muted">{r.user_count} user{r.user_count === 1 ? '' : 's'} · created {formatDateTime(r.created_at)} · updated {formatDateTime(r.updated_at)}</p>

        <Card title="Permissions" padding="none" actions={<ConfigTag />}
          description="Role → permission + scope. ALL: every matching record. OWN: only records tied to the user's own staff member.">
          {r.is_superuser ? <EmptyState compact icon="shieldCheck" title="Implicitly holds every permission"
            description="The system role holds all permissions, present and future, at ALL scope. It cannot be edited." />
            : r.permissions.length === 0 ? <EmptyState compact icon="lock" title="No permissions granted" />
              : domains.map((domain) => (
                <div key={domain}>
                  <div className="grant-domain">{domain.replace(/_/g, ' ')}</div>
                  <ul className="grant-group">
                    {r.permissions.filter((g) => permissionDomain(g.code) === domain).map((g) => (
                      <li className="grant-row" key={g.code}>
                        <span className="mono">{g.code}</span>
                        <span className="grant-row__desc">{describe.get(g.code) ?? ''}</span>
                        <ScopeBadge scope={g.scope} />
                        {editGrants ? (
                          <span className="action-bar">
                            <Button size="sm" variant="ghost" onClick={() => setDialog({ rescope: g })}>
                              Set {g.scope === 'ALL' ? 'OWN' : 'ALL'}</Button>
                            <Button size="sm" variant="danger-ghost" onClick={() => setDialog({ revoke: g })}>Revoke</Button>
                          </span>
                        ) : <span />}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
          {editGrants ? (
            <div className="card-inset">
              <div className="cluster">
                <Field label="Grant permission">
                  <Select value={grantCode} onChange={(e) => setGrantCode(e.target.value)}>
                    <option value="">Select a permission…</option>
                    {ungranted.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.description}</option>)}
                  </Select>
                </Field>
                <Field label="Scope">
                  <Select value={grantScope} onChange={(e) => setGrantScope(e.target.value as 'ALL' | 'OWN')}>
                    <option value="ALL">ALL · all records</option>
                    <option value="OWN">OWN · own records only</option>
                  </Select>
                </Field>
                <Button variant="primary" disabled={!grantCode} loading={action.submitting}
                  onClick={async () => { if (await mutate(() => accessApi.grant(r.id, grantCode, grantScope))) setGrantCode('') }}>Grant</Button>
              </div>
            </div>
          ) : null}
        </Card>
      </div>

      {dialog === 'edit' ? (
        <ActionDialog open title={`Edit ${r.name}`} confirmLabel="Save" onClose={() => setDialog(null)} onDone={role.reload}
          fields={[{ name: 'name', label: 'Name', kind: 'text', required: true, defaultValue: r.name },
            { name: 'description', label: 'Description', kind: 'textarea', defaultValue: r.description ?? '' }]}
          submit={(v) => {
            const body: { name?: string; description?: string | null } = {}
            if (v.name.trim().toUpperCase() !== r.name) body.name = v.name.trim()
            if ((v.description ?? '') !== (r.description ?? '')) body.description = v.description.trim() || null
            return accessApi.updateRole(r.id, body)
          }} />
      ) : null}
      <ConfirmDialog open={dialog === 'deactivate'} title="Deactivate role" confirmLabel="Deactivate" busy={action.submitting}
        onCancel={() => setDialog(null)} onConfirm={() => mutate(() => accessApi.roleAction(r.id, 'deactivate'))}>
        <p>Users holding <strong>{r.name}</strong> lose its permissions immediately ({r.user_count} user{r.user_count === 1 ? '' : 's'}).</p>
      </ConfirmDialog>
      <ConfirmDialog open={dialog === 'reactivate'} title="Reactivate role" confirmLabel="Reactivate" tone="primary" busy={action.submitting}
        onCancel={() => setDialog(null)} onConfirm={() => mutate(() => accessApi.roleAction(r.id, 'reactivate'))}>
        <p>Users holding <strong>{r.name}</strong> regain its permissions.</p>
      </ConfirmDialog>
      <ConfirmDialog open={Boolean(dialog && typeof dialog === 'object' && 'rescope' in dialog)} title="Change scope" confirmLabel="Change scope"
        tone="primary" busy={action.submitting} onCancel={() => setDialog(null)}
        onConfirm={() => {
          if (dialog && typeof dialog === 'object' && 'rescope' in dialog) {
            const g = dialog.rescope
            void mutate(() => accessApi.grant(r.id, g.code, g.scope === 'ALL' ? 'OWN' : 'ALL'))
          }
        }}>
        {dialog && typeof dialog === 'object' && 'rescope' in dialog ? (
          <p>Change <strong className="mono">{dialog.rescope.code}</strong> on {r.name} from {dialog.rescope.scope} to{' '}
            {dialog.rescope.scope === 'ALL' ? 'OWN (only records tied to the user\'s own staff member)' : 'ALL (every matching record)'}?
            Users holding this role are affected immediately.</p>
        ) : null}
      </ConfirmDialog>
      <ConfirmDialog open={Boolean(dialog && typeof dialog === 'object' && 'revoke' in dialog)} title="Revoke permission" confirmLabel="Revoke" busy={action.submitting}
        onCancel={() => setDialog(null)}
        onConfirm={() => { if (dialog && typeof dialog === 'object' && 'revoke' in dialog) void mutate(() => accessApi.revoke(r.id, dialog.revoke.code)) }}>
        <p>Revoke <strong className="mono">{dialog && typeof dialog === 'object' && 'revoke' in dialog ? dialog.revoke.code : ''}</strong> from {r.name}? Users holding this
          role lose it immediately.</p>
      </ConfirmDialog>
    </AdminGuard>
  )
}

/** The permission catalog, with which roles grant each permission and at which scope. */
export function PermissionsPage() {
  const catalog = useQuery((s) => accessApi.permissions(s), [])
  const roles = useQuery((s) => accessApi.roles({ limit: 100 }, s), [])
  const [domain, setDomain] = useState('')
  const all = catalog.data ?? []
  const domains = [...new Set(all.map((p) => permissionDomain(p.code)))].sort()
  const rows = all.filter((p) => !domain || permissionDomain(p.code) === domain)
  const grantedBy = (code: string) => (roles.data?.items ?? []).flatMap((r) => {
    const g = r.permissions.find((p) => p.code === code)
    return g ? [{ role: r, scope: g.scope }] : []
  })
  const superRoles = (roles.data?.items ?? []).filter((r) => r.is_superuser)
  return (
    <AdminGuard anyOf={ROLE_READERS}>
      <div className="admin-head">
        <div className="admin-head__title"><h2>Permission catalog</h2><ConfigTag /></div>
        <div className="section-filters">
          <Field label="Area">
            <Select value={domain} onChange={(e) => setDomain(e.target.value)}>
              <option value="">All areas</option>
              {domains.map((d) => <option key={d} value={d}>{d.replace(/_/g, ' ')}</option>)}
            </Select>
          </Field>
        </div>
      </div>
      {superRoles.length ? <Alert tone="info" title="System role">{superRoles.map((r) => r.name).join(', ')} implicitly holds every permission at ALL scope
        and is not listed per permission below.</Alert> : null}
      <Card padding="none">
        {catalog.error ? <ErrorState error={catalog.error} onRetry={catalog.reload} /> : (
          <DataTable caption="Permissions" rows={catalog.data ? rows : undefined} rowKey={(p) => p.code} loading={catalog.loading && !catalog.data}
            empty={<EmptyState icon="lock" title="No permissions" />}
            columns={[
              { key: 'code', header: 'Permission', render: (p) => <span className="cell-stack"><span className="mono cell-strong">{p.code}</span>
                <span className="cell-sub">{p.description}</span></span> },
              { key: 'roles', header: 'Granted by (scope)', render: (p) => {
                const list = grantedBy(p.code)
                if (roles.error) return <span className="text-subtle">Roles unavailable</span>
                if (!list.length) return <span className="text-subtle">No role</span>
                return <span className="chips-inline">{list.map(({ role, scope }) => (
                  <span key={role.id} className="cluster" style={{ gap: 4 }}>
                    <RoleLink role={role} />{role.status !== 'ACTIVE' ? <span className="text-subtle">(inactive)</span> : null}<ScopeBadge scope={scope} />
                  </span>))}</span>
              } },
            ]} />
        )}
      </Card>
    </AdminGuard>
  )
}
