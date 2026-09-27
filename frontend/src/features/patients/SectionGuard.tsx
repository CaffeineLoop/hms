import type { ReactNode } from 'react'
import { useAuth } from '../../auth/useAuth'
import { Card, EmptyState } from '../../components/ui'

/**
 * Renders a clinical record section only for users the backend would let read it: one of `permission` together with
 * patient.view, both at ALL scope (the backend clinical-read rule; OWN grants no access). The backend still decides —
 * without access the API returns 403. Direct URL access shows an access message instead.
 */
export function SectionGuard({ permission, children }: { permission: string | readonly string[]; children: ReactNode }) {
  const { canReadClinical } = useAuth()
  const codes = typeof permission === 'string' ? [permission] : permission
  if (!codes.some(canReadClinical)) {
    return (
      <Card>
        <EmptyState icon="lock" title="Not available for your role"
          description={`This part of the record requires ${codes.join(' or ')} (with patient.view) for all patients.`} />
      </Card>
    )
  }
  return <>{children}</>
}
