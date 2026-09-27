/** Accessible tabs (WAI-ARIA tabs pattern): roving tabindex, Arrow/Home/End keys, linked panels. */
import { useId, useRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import './Tabs.css'

export interface TabItem {
  id: string
  label: ReactNode
  count?: number
}

interface TabsProps {
  items: TabItem[]
  value: string
  onChange: (id: string) => void
  label: string
  children?: ReactNode
}

export function Tabs({ items, value, onChange, label, children }: TabsProps) {
  const baseId = useId()
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((t) => t.id === value)
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: items.length - 1 }[event.key]
    if (next === undefined) return
    event.preventDefault()
    const target = (next + items.length) % items.length
    onChange(items[target].id)
    refs.current[target]?.focus()
  }

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {items.map((tab, i) => {
          const selected = tab.id === value
          return (
            <button key={tab.id} ref={(el) => { refs.current[i] = el }} type="button" role="tab"
              id={`${baseId}-tab-${tab.id}`} aria-selected={selected} aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1} className={['tabs__tab', selected ? 'is-selected' : ''].join(' ')}
              onClick={() => onChange(tab.id)}>
              {tab.label}
              {tab.count !== undefined ? <span className="tabs__count tabular">{tab.count}</span> : null}
            </button>
          )
        })}
      </div>
      {children !== undefined ? (
        <div className="tabs__panel" role="tabpanel" id={`${baseId}-panel-${value}`} aria-labelledby={`${baseId}-tab-${value}`}
          tabIndex={0}>
          {children}
        </div>
      ) : null}
    </div>
  )
}
