import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../icons/Icon'
import './PageHeader.css'

export interface Crumb {
  label: string
  to?: string
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length === 0) return null
  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      <ol>
        {items.map((crumb, i) => {
          const last = i === items.length - 1
          return (
            <li key={`${crumb.label}-${i}`}>
              {crumb.to && !last ? <Link to={crumb.to}>{crumb.label}</Link>
                : <span aria-current={last ? 'page' : undefined}>{crumb.label}</span>}
              {!last ? <Icon name="chevronRight" size={14} className="breadcrumbs__sep" /> : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  breadcrumbs?: Crumb[]
  actions?: ReactNode
  meta?: ReactNode
}

/** Consistent top of every page: breadcrumbs, title, supporting line, primary actions. */
export function PageHeader({ title, description, breadcrumbs, actions, meta }: PageHeaderProps) {
  return (
    <header className="page-header">
      {breadcrumbs ? <Breadcrumbs items={breadcrumbs} /> : null}
      <div className="page-header__row">
        <div className="page-header__text">
          <h1 className="page-header__title">{title}</h1>
          {description ? <p className="page-header__description">{description}</p> : null}
          {meta ? <div className="page-header__meta">{meta}</div> : null}
        </div>
        {actions ? <div className="page-header__actions">{actions}</div> : null}
      </div>
    </header>
  )
}
