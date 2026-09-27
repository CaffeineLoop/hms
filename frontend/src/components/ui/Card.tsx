import type { ReactNode } from 'react'
import './Card.css'

interface CardProps {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  footer?: ReactNode
  padding?: 'none' | 'md'
  children?: ReactNode
  className?: string
  as?: 'section' | 'div'
}

/** Surface for grouped content: header (title/description/actions), body, optional footer. */
export function Card({ title, description, actions, footer, padding = 'md', children, className, as = 'section' }: CardProps) {
  const Tag = as
  return (
    <Tag className={['card', className ?? ''].join(' ')}>
      {title || actions ? (
        <header className="card__header">
          <div className="card__heading">
            {title ? <h2 className="card__title">{title}</h2> : null}
            {description ? <p className="card__description">{description}</p> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={`card__body card__body--${padding}`}>{children}</div>
      {footer ? <footer className="card__footer">{footer}</footer> : null}
    </Tag>
  )
}
