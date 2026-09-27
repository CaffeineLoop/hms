import type { ReactNode } from 'react'
import { humanize } from '../../lib/format'
import './Badge.css'

export type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps {
  tone?: Tone
  variant?: 'subtle' | 'outline' | 'solid'
  dot?: boolean
  size?: 'sm' | 'md'
  children: ReactNode
}

export function Badge({ tone = 'neutral', variant = 'subtle', dot, size = 'md', children }: BadgeProps) {
  return (
    <span className={`badge badge--${tone} badge--${variant} badge--${size}`}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  )
}

/** Semantic mapping of HMS domain states to tones — one place, used everywhere. */
const STATUS_TONES: Record<string, Tone> = {
  // workflow tasks
  OPEN: 'info', ASSIGNED: 'info', IN_PROGRESS: 'primary', COMPLETED: 'success', CANCELLED: 'neutral',
  // priorities
  LOW: 'neutral', NORMAL: 'neutral', HIGH: 'warning', URGENT: 'danger', STAT: 'danger', ROUTINE: 'neutral',
  MODERATE: 'warning',
  // clinical record / order lifecycles
  ACTIVE: 'success', INACTIVE: 'neutral', RESOLVED: 'neutral', SUSPECTED: 'warning', HISTORICAL: 'neutral',
  DRAFT: 'neutral', ON_HOLD: 'warning', RELEASED: 'success', VERIFIED: 'info', ORDERED: 'info',
  PLANNED: 'info', FINISHED: 'neutral', ADMITTED: 'primary', DISCHARGED: 'neutral', REQUESTED: 'info',
  // AI review pathway
  PENDING_REVIEW: 'warning', ACKNOWLEDGED: 'success', DISMISSED: 'neutral', ABSTAINED: 'neutral',
  // audit outcomes
  SUCCESS: 'success', FAILURE: 'warning', DENIED: 'danger',
}

export function StatusBadge({ status, size = 'md', label }: { status: string; size?: 'sm' | 'md'; label?: string }) {
  return (
    <Badge tone={STATUS_TONES[status] ?? 'neutral'} dot size={size}>
      {label ?? humanize(status)}
    </Badge>
  )
}
