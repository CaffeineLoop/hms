import type { ReactNode } from 'react'
import './DescriptionList.css'

export interface DescriptionItem {
  label: string
  value: ReactNode
  /** Span the full row (long text). */
  wide?: boolean
}

/**
 * Labelled record details. Empty values show an explicit "Not recorded" (never a blank that could be misread
 * as "none" or "normal").
 */
export function DescriptionList({ items, columns = 2 }: { items: DescriptionItem[]; columns?: 1 | 2 | 3 }) {
  return (
    <dl className={`dlist dlist--${columns}`}>
      {items.map((item) => (
        <div key={item.label} className={['dlist__item', item.wide ? 'dlist__item--wide' : ''].join(' ')}>
          <dt>{item.label}</dt>
          <dd>{item.value === null || item.value === undefined || item.value === ''
            ? <span className="dlist__empty">Not recorded</span> : item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
