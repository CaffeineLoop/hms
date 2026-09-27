/**
 * UI-4 Administration: users, roles, permission catalog and the audit trail (Stage 5/6 APIs). Each area is shown
 * only to users holding its permission, and each page is guarded again at route level; the backend remains the
 * authority (anti-escalation rules, system roles, last superuser, ...).
 */
import { Navigate, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { Card, EmptyState, PageHeader } from '../../components/ui'
import '../patients/patients.css'
import './admin.css'

const ADMIN_AREAS = [
  { path: 'users', label: 'Users', anyOf: ['user.view'] },
  { path: 'roles', label: 'Roles', anyOf: ['role.manage', 'permission.manage'] },
  { path: 'permissions', label: 'Permissions', anyOf: ['role.manage', 'permission.manage'] },
  { path: 'audit', label: 'Audit trail', anyOf: ['audit.view'] },
] as const

export function AdminLayout() {
  const { canAny } = useAuth()
  const areas = ADMIN_AREAS.filter((a) => canAny(...a.anyOf))
  return (
    <>
      <PageHeader title="Administration" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Administration' }]}
        description="User accounts, role-based access and the audit trail. Every change is checked and recorded by the HMS." />
      {areas.length === 0 ? (
        <Card><EmptyState icon="lock" title="Not available for your role"
          description="Administration requires user.view, role.manage, permission.manage or audit.view." /></Card>
      ) : (
        <>
          <nav className="tabs" aria-label="Administration areas">
            <div className="tabs__list">
              {areas.map((a) => (
                <NavLink key={a.path} to={`/administration/${a.path}`}
                  className={({ isActive }) => ['tabs__tab', isActive ? 'is-selected' : ''].join(' ')}>{a.label}</NavLink>
              ))}
            </div>
          </nav>
          <div className="precord__section"><Outlet /></div>
        </>
      )}
    </>
  )
}

export function AdminIndex() {
  const { canAny } = useAuth()
  const first = ADMIN_AREAS.find((a) => canAny(...a.anyOf))
  return first ? <Navigate to={`/administration/${first.path}`} replace /> : null
}
