/**
 * Route-based tabs (each tab is a link to a sub-route), styled identically to <Tabs>. Use for page sections that
 * should be addressable (bookmarkable, back-button friendly), e.g. the patient record.
 */
import { useEffect, useRef } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import './Tabs.css'

export interface TabNavItem {
  to: string
  label: string
  end?: boolean
}

export function TabNav({ items, label }: { items: TabNavItem[]; label: string }) {
  const listRef = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()
  // On narrow screens the tab row scrolls horizontally: keep the selected tab in view.
  useEffect(() => {
    const list = listRef.current
    const selected = list?.querySelector<HTMLElement>('.is-selected')
    if (!list || !selected) return
    const left = selected.offsetLeft - list.offsetLeft
    if (left < list.scrollLeft || left + selected.offsetWidth > list.scrollLeft + list.clientWidth) {
      list.scrollLeft = left - (list.clientWidth - selected.offsetWidth) / 2
    }
  }, [pathname])
  return (
    <nav className="tabs" aria-label={label}>
      <div className="tabs__list" ref={listRef}>
        {items.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}
            className={({ isActive }) => ['tabs__tab', isActive ? 'is-selected' : ''].join(' ')}>
            {item.label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
