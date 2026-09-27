/**
 * My account (UI-4): who I am, my effective access, change password and sign out of every session.
 * POST /api/auth/change-password keeps this session and revokes the others; POST /api/auth/logout-all revokes all.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { authApi } from '../../api/endpoints'
import { useAuth } from '../../auth/useAuth'
import { Alert, Badge, Button, Card, ConfirmDialog, DescriptionList, Field, Input, PageHeader } from '../../components/ui'
import { useSubmit } from '../../hooks/useSubmit'
import { humanize } from '../../lib/format'
import { ConfigTag, SessionTag } from '../admin/accessUi'
import { GrantList } from '../admin/UsersPages'
import { ProblemAlert } from '../writes/WriteControls'
import '../patients/patients.css'
import '../admin/admin.css'

export function AccountPage() {
  const { user, logoutAll } = useAuth()
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [changed, setChanged] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)
  const pw = useSubmit()
  const all = useSubmit()
  if (!user) return null
  const set = (field: keyof typeof form) => (value: string) => { setForm((f) => ({ ...f, [field]: value })); pw.clearField(field); setChanged(false) }

  async function onChange(event: FormEvent) {
    event.preventDefault()
    const missing: Record<string, string> = {}
    if (!form.current_password) missing.current_password = 'Enter your current password.'
    if (!form.new_password) missing.new_password = 'Enter a new password.'
    if (form.new_password && form.confirm !== form.new_password) missing.confirm = 'The two new passwords do not match.'
    if (Object.keys(missing).length) return pw.reject(missing, 'Your password has not been changed.')
    const ok = await pw.run(async () => { await authApi.changePassword(form.current_password, form.new_password); return true })
    if (ok) { setForm({ current_password: '', new_password: '', confirm: '' }); setChanged(true) }
  }

  return (
    <>
      <PageHeader title="My account" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'My account' }]}
        description="Your profile, your access and your sign-in security." />
      <div className="stack">
        <Card title="Profile" actions={<ConfigTag>Account</ConfigTag>}>
          <DescriptionList columns={3} items={[
            { label: 'Name', value: user.staff.full_name },
            { label: 'Username', value: <span className="mono">{user.username}</span> },
            { label: 'Employee code', value: <span className="mono">{user.staff.employee_code}</span> },
            { label: 'Designation', value: humanize(user.staff.designation) },
            { label: 'Roles', value: user.is_superuser ? <Badge tone="danger" size="sm">Super administrator</Badge>
              : user.roles.length ? <span className="chips-inline">{user.roles.map((r) => <Badge key={r} size="sm">{r}</Badge>)}</span> : 'No roles' },
          ]} />
        </Card>

        <Card title="My access" padding="none" actions={<ConfigTag />}
          description="Your effective permissions through your active roles, as reported by the HMS at sign-in.">
          {user.is_superuser
            ? <div className="card-inset"><Alert tone="info" title="Super administrator">You hold every permission at ALL scope.</Alert></div>
            : user.permissions.length ? <GrantList grants={user.permissions} /> : <p className="card-inset text-muted">You have no permissions.</p>}
        </Card>

        <Card title="Change password" actions={<SessionTag />}
          description="Your other sessions are signed out when the password changes; this one stays signed in.">
          <form className="stack" onSubmit={onChange} noValidate style={{ maxWidth: 480 }}>
            <ProblemAlert problem={pw.problem} />
            {changed ? <Alert tone="success" title="Password changed">Your other sessions have been signed out.</Alert> : null}
            <Field label="Current password" required error={pw.errors.current_password}>
              <Input type="password" autoComplete="current-password" value={form.current_password} onChange={(e) => set('current_password')(e.target.value)} />
            </Field>
            <Field label="New password" required error={pw.errors.new_password}
              hint="At least 12 characters, not repetitive, not containing your username (checked by the HMS)">
              <Input type="password" autoComplete="new-password" value={form.new_password} onChange={(e) => set('new_password')(e.target.value)} />
            </Field>
            <Field label="Confirm new password" required error={pw.errors.confirm}>
              <Input type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => set('confirm')(e.target.value)} />
            </Field>
            <div><Button type="submit" variant="primary" loading={pw.submitting}>Change password</Button></div>
          </form>
        </Card>

        <Card title="Sessions" actions={<SessionTag />}
          description="Sign out of the HMS on every device and browser, including this one.">
          <ProblemAlert problem={all.problem} />
          <Button variant="danger" icon="logout" onClick={() => setConfirmAll(true)}>Sign out of all sessions</Button>
        </Card>
      </div>
      <ConfirmDialog open={confirmAll} title="Sign out of all sessions" confirmLabel="Sign out everywhere" busy={all.submitting}
        onCancel={() => setConfirmAll(false)}
        onConfirm={async () => { await all.run(async () => { await logoutAll(); return true }); setConfirmAll(false) }}>
        <p>Every session of your account ends immediately, on all devices. You will need to sign in again.</p>
      </ConfirmDialog>
    </>
  )
}
