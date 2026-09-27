/**
 * Users (GET/POST /api/users...). Accounts are linked to staff members; the list shows what UserRead exposes.
 * Session information is limited to what the API returns (last sign-in, password change) — active sessions are not
 * listed by the backend. Anti-escalation (no changes to your own account, only grantable roles, last superuser) is
 * enforced by the backend; the UI shows its answer.
 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { accessApi } from '../../api/endpoints'
import type { Role, UserAccount } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { Column } from '../../components/ui'
import {
  Alert, Badge, Button, Card, ConfirmDialog, DataTable, DescriptionList, EmptyState, ErrorState, Field, Input,
  LinkButton, LoadingState, Pagination, Select, StatusBadge,
} from '../../components/ui'
import { useDebounced } from '../../hooks/useDebounced'
import { useQuery } from '../../hooks/useQuery'
import { useSubmit } from '../../hooks/useSubmit'
import { effectiveGrants, permissionDomain } from '../../lib/access'
import { formatDateTime, formatRelative } from '../../lib/format'
import { StaffName } from '../patients/shared'
import { ActionDialog, ProblemAlert } from '../writes/WriteControls'
import { AdminGuard, ConfigTag, RoleLink, ScopeBadge, SessionTag } from './accessUi'

const PAGE_SIZE = 25

function RoleBadges({ roles }: { roles: UserAccount['roles'] }) {
  if (!roles.length) return <span className="text-subtle">No roles</span>
  return (
    <span className="chips-inline">
      {roles.map((r) => (
        <Badge key={r.id} tone={r.is_superuser ? 'danger' : r.status === 'ACTIVE' ? 'neutral' : 'warning'} size="sm">
          <RoleLink role={r} />{r.status !== 'ACTIVE' ? ' (inactive)' : ''}
        </Badge>
      ))}
    </span>
  )
}

export function UsersPage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const search = useDebounced(q, 300)
  const result = useQuery((s) => accessApi.users({ q: search || undefined, status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [search, status, offset])
  const columns: Column<UserAccount>[] = [
    { key: 'username', header: 'Username', render: (u) => <span className="mono cell-strong">{u.username}</span> },
    { key: 'staff', header: 'Staff member', render: (u) => <StaffName staffId={u.staff_id} /> },
    { key: 'roles', header: 'Roles', render: (u) => <RoleBadges roles={u.roles} /> },
    { key: 'status', header: 'Status', render: (u) => <StatusBadge status={u.status} size="sm" /> },
    { key: 'login', header: 'Last sign-in', numeric: true, priority: 'secondary',
      render: (u) => (u.last_login_at ? formatRelative(u.last_login_at) : <span className="text-subtle">Never</span>) },
  ]
  return (
    <AdminGuard anyOf={['user.view']}>
      <div className="admin-head">
        <div className="admin-head__title"><h2>User accounts</h2><ConfigTag /></div>
        <div className="section-filters">
          <Field label="Search"><Input type="search" icon="search" value={q} placeholder="Username"
            onChange={(e) => { setQ(e.target.value); setOffset(0) }} /></Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All statuses</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </Select>
          </Field>
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="User accounts" columns={columns} rows={result.data?.items} rowKey={(u) => u.id}
              loading={result.loading && !result.data} onRowClick={(u) => navigate(`/administration/users/${u.id}`)}
              rowLabel={(u) => `Open user ${u.username}`}
              empty={<EmptyState icon="user" title={q || status ? 'No users match these filters' : 'No user accounts'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="users" /> : null}
          </>
        )}
      </Card>
    </AdminGuard>
  )
}

export function UserDetailPage() {
  const { userId = '' } = useParams()
  const { user: me, can, canAny } = useAuth()
  const account = useQuery((s) => accessApi.user(userId, s), [userId])
  const canReadRoles = canAny('role.manage', 'permission.manage')
  const roles = useQuery((s) => accessApi.roles({ limit: 100 }, s), [], { enabled: canReadRoles })
  const [dialog, setDialog] = useState<null | 'deactivate' | 'reactivate' | 'reset' | { remove: UserAccount['roles'][number] }>(null)
  const [assignId, setAssignId] = useState('')
  const action = useSubmit()
  const back = <LinkButton to="/administration/users" variant="ghost" size="sm" icon="chevronLeft">All users</LinkButton>

  if (account.error) return <AdminGuard anyOf={['user.view']}><Card>{back}<ErrorState error={account.error} /></Card></AdminGuard>
  if (!account.data) return <AdminGuard anyOf={['user.view']}><LoadingState label="Loading user…" /></AdminGuard>
  const u = account.data
  const self = me?.user_id === u.id
  const manage = can('user.manage')
  const heldRoles: Role[] = (roles.data?.items ?? []).filter((r) => u.roles.some((ur) => ur.id === r.id))
  const superuser = u.roles.some((r) => r.is_superuser && r.status === 'ACTIVE')
  const grants = effectiveGrants(heldRoles)
  const assignable = (roles.data?.items ?? []).filter((r) => r.status === 'ACTIVE' && !u.roles.some((ur) => ur.id === r.id))

  async function mutate(write: () => Promise<unknown>) {
    const ok = await action.run(async () => { await write(); return true })
    setDialog(null)
    if (ok) { account.reload(); roles.reload() }
  }

  return (
    <AdminGuard anyOf={['user.view']}>
      <div className="stack">
        <div>{back}</div>
        <div className="admin-head">
          <div className="admin-head__title"><h2 className="mono">{u.username}</h2><StatusBadge status={u.status} size="sm" /><ConfigTag /></div>
          {manage && !self ? (
            <div className="action-bar">
              <Button size="sm" onClick={() => setDialog('reset')}>Reset password</Button>
              {u.status === 'ACTIVE'
                ? <Button size="sm" variant="danger-ghost" onClick={() => setDialog('deactivate')}>Deactivate account</Button>
                : <Button size="sm" variant="primary" onClick={() => setDialog('reactivate')}>Reactivate account</Button>}
            </div>
          ) : null}
        </div>
        {self ? <Alert tone="info" title="This is your own account">The HMS does not let administrators change their own roles, status or
          password here. Use <strong>My account</strong> to change your password.</Alert> : null}
        <ProblemAlert problem={action.problem} />

        <Card title="Account" actions={<ConfigTag>Account</ConfigTag>}>
          <DescriptionList columns={3} items={[
            { label: 'Username', value: <span className="mono">{u.username}</span> },
            { label: 'Staff member', value: <StaffName staffId={u.staff_id} /> },
            { label: 'Status', value: <StatusBadge status={u.status} size="sm" /> },
            { label: 'Created', value: formatDateTime(u.created_at) },
            { label: 'Deactivated', value: u.deactivated_at ? formatDateTime(u.deactivated_at) : null },
          ]} />
        </Card>

        <Card title="Sign-in and sessions" actions={<SessionTag />}
          description="As reported by the HMS. Individual active sessions are not listed by the API.">
          <DescriptionList columns={3} items={[
            { label: 'Last sign-in', value: u.last_login_at ? `${formatDateTime(u.last_login_at)} (${formatRelative(u.last_login_at)})` : 'Never signed in' },
            { label: 'Password last changed', value: formatDateTime(u.password_changed_at) },
          ]} />
        </Card>

        <Card title="Roles" padding="none" actions={<ConfigTag />}
          description="User → role assignments. Inactive roles grant nothing.">
          {u.roles.length === 0 ? <EmptyState compact icon="user" title="No roles assigned" description="The account can sign in but has no permissions." /> : (
            <ul className="grant-group">
              {u.roles.map((r) => (
                <li className="grant-row" key={r.id}>
                  <span className="cell-strong"><RoleLink role={r} /></span>
                  <span className="grant-row__desc">{r.is_superuser ? 'System role — implicitly holds every permission' : ''}</span>
                  <StatusBadge status={r.status} size="sm" />
                  {manage && !self ? <Button size="sm" variant="danger-ghost" onClick={() => setDialog({ remove: r })}>Remove</Button> : <span />}
                </li>
              ))}
            </ul>
          )}
          {manage && !self ? (
            <div className="card-inset">
              {canReadRoles ? (
                <div className="cluster">
                  <Field label="Assign a role">
                    <Select value={assignId} onChange={(e) => setAssignId(e.target.value)}>
                      <option value="">Select a role…</option>
                      {assignable.map((r) => <option key={r.id} value={r.id}>{r.name}{r.is_superuser ? ' (system)' : ''}</option>)}
                    </Select>
                  </Field>
                  <Button variant="primary" disabled={!assignId} loading={action.submitting}
                    onClick={() => mutate(() => accessApi.assignRole(u.id, assignId)).then(() => setAssignId(''))}>Assign role</Button>
                </div>
              ) : <p className="text-muted">Assigning roles needs the role list, which requires role.manage or permission.manage.</p>}
            </div>
          ) : null}
        </Card>

        <Card title="Effective access" padding="none" actions={<ConfigTag />}
          description="Union of the permissions of this user's active roles; each permission at its broadest scope.">
          {superuser ? <div className="card-inset"><Alert tone="info" title="Super administrator">Holds every permission, present and future, at ALL scope.</Alert></div>
            : !canReadRoles ? <EmptyState compact icon="lock" title="Role permissions are visible to role administrators"
              description="Viewing role grants requires role.manage or permission.manage." />
              : roles.error ? <ErrorState compact error={roles.error} />
                : !roles.data ? <LoadingState rows={3} />
                  : grants.length === 0 ? <EmptyState compact icon="lock" title="No effective permissions" />
                    : <GrantList grants={grants} />}
        </Card>
      </div>

      <ConfirmDialog open={dialog === 'deactivate'} title="Deactivate account" confirmLabel="Deactivate" busy={action.submitting}
        onCancel={() => setDialog(null)} onConfirm={() => mutate(() => accessApi.userAction(u.id, 'deactivate'))}>
        <p><strong className="mono">{u.username}</strong> will no longer be able to sign in and all of their sessions end. The account and its history are kept.</p>
      </ConfirmDialog>
      <ConfirmDialog open={dialog === 'reactivate'} title="Reactivate account" confirmLabel="Reactivate" tone="primary" busy={action.submitting}
        onCancel={() => setDialog(null)} onConfirm={() => mutate(() => accessApi.userAction(u.id, 'reactivate'))}>
        <p><strong className="mono">{u.username}</strong> will be able to sign in again with their existing roles.</p>
      </ConfirmDialog>
      <ConfirmDialog open={typeof dialog === 'object' && dialog !== null} title="Remove role" confirmLabel="Remove role" busy={action.submitting}
        onCancel={() => setDialog(null)}
        onConfirm={() => { if (dialog && typeof dialog === 'object') void mutate(() => accessApi.removeRole(u.id, dialog.remove.id)) }}>
        <p>Remove <strong>{dialog && typeof dialog === 'object' ? dialog.remove.name : ''}</strong> from <span className="mono">{u.username}</span>?
          Their access changes immediately.</p>
      </ConfirmDialog>
      <ActionDialog open={dialog === 'reset'} title={`Reset password for ${u.username}`} confirmLabel="Reset password" tone="danger"
        description="Sets a new password and ends all of the user's sessions. Share it securely and ask the user to change it."
        fields={[{ name: 'new_password', label: 'New password', kind: 'password', required: true,
          hint: 'At least 12 characters; not containing the username (checked by the HMS)' }]}
        onClose={() => setDialog(null)} onDone={account.reload}
        submit={(v) => accessApi.resetPassword(u.id, v.new_password)} />
    </AdminGuard>
  )
}

export function GrantList({ grants, describe }: { grants: Array<{ code: string; scope: 'ALL' | 'OWN' }>; describe?: Map<string, string> }) {
  const domains = [...new Set(grants.map((g) => permissionDomain(g.code)))].sort()
  return (
    <div>
      {domains.map((domain) => (
        <div key={domain}>
          <div className="grant-domain">{domain.replace(/_/g, ' ')}</div>
          <ul className="grant-group">
            {grants.filter((g) => permissionDomain(g.code) === domain).map((g) => (
              <li className="grant-row" key={g.code}>
                <span className="mono">{g.code}</span>
                <span className="grant-row__desc">{describe?.get(g.code) ?? ''}</span>
                <ScopeBadge scope={g.scope} />
                <span />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
