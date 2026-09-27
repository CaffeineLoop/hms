/** Empty, loading and error states — every data region uses these so behaviour is predictable. */
import type { ReactNode } from 'react'
import type { ApiError } from '../../api/client'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import { Button } from './Button'
import { Skeleton, Spinner } from './Spinner'
import './States.css'

interface EmptyStateProps {
  icon?: IconName
  title: string
  description?: ReactNode
  action?: ReactNode
  compact?: boolean
}

export function EmptyState({ icon = 'inbox', title, description, action, compact }: EmptyStateProps) {
  return (
    <div className={['state', compact ? 'state--compact' : ''].join(' ')}>
      <span className="state__icon"><Icon name={icon} size={compact ? 18 : 22} /></span>
      <p className="state__title">{title}</p>
      {description ? <p className="state__description">{description}</p> : null}
      {action ? <div className="state__action">{action}</div> : null}
    </div>
  )
}

export function LoadingState({ label = 'Loading…', rows = 0 }: { label?: string; rows?: number }) {
  if (rows > 0) {
    return (
      <div className="state-skeleton" role="status" aria-label={label}>
        {Array.from({ length: rows }, (_, i) => (
          <div className="state-skeleton__row" key={i}>
            <Skeleton width="28%" height={11} />
            <Skeleton width={i % 2 ? '52%' : '40%'} height={11} />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="state state--compact" role="status">
      <Spinner size={18} />
      <p className="state__description">{label}</p>
    </div>
  )
}

/** Error state. 403 is shown as an access message (not an error) — permissions are expected, not failures. */
export function ErrorState({ error, onRetry, compact }: { error: ApiError | null; onRetry?: () => void; compact?: boolean }) {
  if (error?.isForbidden) {
    return (
      <EmptyState compact={compact} icon="lock" title="Not available for your role"
        description="Your account does not include the permission needed to view this information." />
    )
  }
  return (
    <div className={['state', 'state--error', compact ? 'state--compact' : ''].join(' ')} role="alert">
      <span className="state__icon"><Icon name="alert" size={compact ? 18 : 22} /></span>
      <p className="state__title">Unable to load this information</p>
      <p className="state__description">{error?.message ?? 'Something went wrong.'}</p>
      {onRetry ? <div className="state__action"><Button size="sm" icon="refresh" onClick={onRetry}>Try again</Button></div> : null}
    </div>
  )
}
