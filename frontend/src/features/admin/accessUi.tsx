/** Shared presentation for access administration: scope badges, tags and permission grouping. Display only. */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Scope } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Badge, Card, EmptyState } from '../../components/ui'
import { Icon } from '../../components/icons/Icon'

/** ALL = every matching record; OWN = only records tied to the user's own staff member (backend semantics). */
export function ScopeBadge({ scope }: { scope: Scope }) {
  return scope === 'ALL'
    ? <Badge tone="primary" size="sm"><span title="Every matching record">ALL · all records</span></Badge>
    : <Badge tone="warning" size="sm"><span title="Only records tied to the user's own staff member">OWN · own records only</span></Badge>
}

/** Marks access-configuration content (distinct from audit records and session status). */
export function ConfigTag({ children = 'Access configuration' }: { children?: ReactNode }) {
  return <span className="admin-tag admin-tag--config"><Icon name="shieldCheck" size={13} />{children}</span>
}

export function AuditTag() {
  return <span className="admin-tag admin-tag--audit"><Icon name="document" size={13} />Audit record · read-only</span>
}

export function SessionTag() {
  return <span className="admin-tag admin-tag--session"><Icon name="clock" size={13} />Session status</span>
}

/** Page-level guard: the page renders only with one of `anyOf` (the backend still decides every request). */
export function AdminGuard({ anyOf, children }: { anyOf: string[]; children: ReactNode }) {
  const { canAny } = useAuth()
  if (!canAny(...anyOf)) {
    return <Card><EmptyState icon="lock" title="Not available for your role"
      description={`This page requires ${anyOf.join(' or ')}.`} /></Card>
  }
  return <>{children}</>
}

export function RoleLink({ role }: { role: { id: string; name: string } }) {
  const { canAny } = useAuth()
  return canAny('role.manage', 'permission.manage')
    ? <Link to={`/administration/roles/${role.id}`} onClick={(e) => e.stopPropagation()}>{role.name}</Link>
    : <span>{role.name}</span>
}
