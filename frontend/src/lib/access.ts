/** Access-administration helpers (presentation of backend RBAC data only). */
import type { Grant, Role, Scope } from '../api/types'

/** "patient.view" -> domain "patient". */
export function permissionDomain(code: string): string {
  return code.split('.')[0]
}

/**
 * Effective grants of a set of roles: only ACTIVE roles count, and each permission keeps its broadest scope
 * (ALL over OWN) — the same way the backend resolves a user's permissions. Presentation of backend data only.
 */
export function effectiveGrants(roles: Role[]): Grant[] {
  const byCode = new Map<string, Scope>()
  for (const role of roles) {
    if (role.status !== 'ACTIVE') continue
    for (const grant of role.permissions) {
      if (byCode.get(grant.code) !== 'ALL') byCode.set(grant.code, grant.scope)
    }
  }
  return [...byCode].map(([code, scope]) => ({ code, scope })).sort((a, b) => a.code.localeCompare(b.code))
}
