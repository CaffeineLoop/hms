import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import { Skeleton } from './Spinner'
import './StatCard.css'

interface StatCardProps {
  label: string
  value: number | string | undefined
  icon: IconName
  hint?: ReactNode
  loading?: boolean
  /** Shown instead of a value when the metric is not available to the user (permission) or failed to load. */
  unavailable?: string | null
  to?: string
  tone?: 'default' | 'attention' | 'ai'
}

/** KPI tile. Values always come from the HMS API; nothing is estimated or invented. */
export function StatCard({ label, value, icon, hint, loading, unavailable, to, tone = 'default' }: StatCardProps) {
  const body = (
    <>
      <div className="stat__top">
        <span className="stat__label">{label}</span>
        <span className="stat__icon"><Icon name={icon} size={16} /></span>
      </div>
      <div className="stat__value tabular">
        {loading ? <Skeleton width={56} height={26} /> : unavailable ? <span className="stat__na">—</span> : value}
      </div>
      <div className="stat__hint">{unavailable ?? hint}</div>
    </>
  )
  const className = `stat stat--${tone}${to && !unavailable ? ' stat--link' : ''}`
  return to && !unavailable ? <Link to={to} className={className}>{body}</Link> : <div className={className}>{body}</div>
}
