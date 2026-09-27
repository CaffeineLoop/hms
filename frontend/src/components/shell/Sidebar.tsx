import { NavLink } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { Icon } from '../icons/Icon'
import { NAVIGATION } from './navigation'

interface SidebarProps {
  collapsed: boolean
  mobileOpen: boolean
  onNavigate: () => void
  onToggleCollapsed: () => void
}

export function Sidebar({ collapsed, mobileOpen, onNavigate, onToggleCollapsed }: SidebarProps) {
  const { canAny } = useAuth()
  const groups = NAVIGATION.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.anyOf.length === 0 || canAny(...item.anyOf)),
  })).filter((group) => group.items.length > 0)

  return (
    <aside className={['sidebar', collapsed ? 'is-collapsed' : '', mobileOpen ? 'is-open' : ''].join(' ')} aria-label="Primary">
      <div className="sidebar__brand">
        <span className="sidebar__logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="30" height="30"><rect width="32" height="32" rx="7" fill="#1b7f95" /><path d="M13 8h6v5h5v6h-5v5h-6v-5H8v-6h5z" fill="#fff" /></svg>
        </span>
        <span className="sidebar__brand-text">
          <span className="sidebar__product">HMS</span>
          <span className="sidebar__tagline">Hospital Management</span>
        </span>
      </div>

      <nav className="sidebar__nav">
        {groups.map((group) => (
          <div className="sidebar__group" key={group.label}>
            <p className="sidebar__group-label">{group.label}</p>
            <ul>
              {group.items.map((item) => (
                <li key={item.id}>
                  <NavLink to={item.to} end={item.to === '/'} onClick={onNavigate} title={collapsed ? item.label : undefined}
                    className={({ isActive }) => ['sidebar__link', isActive ? 'is-active' : ''].join(' ')}>
                    <Icon name={item.icon} size={18} />
                    <span className="sidebar__link-label">{item.label}</span>
                    {item.planned ? <span className="sidebar__soon" title="Module planned for a later UI stage">Soon</span> : null}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="sidebar__footer">
        {import.meta.env.DEV ? (
          <NavLink to="/design-system" onClick={onNavigate} title={collapsed ? 'Design system' : undefined}
            className={({ isActive }) => ['sidebar__link', 'sidebar__link--quiet', isActive ? 'is-active' : ''].join(' ')}>
            <Icon name="settings" size={18} />
            <span className="sidebar__link-label">Design system</span>
          </NavLink>
        ) : null}
        <button type="button" className="sidebar__link sidebar__link--quiet sidebar__collapse" onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} title={collapsed ? 'Expand navigation' : undefined}>
          <Icon name={collapsed ? 'expand' : 'collapse'} size={18} />
          <span className="sidebar__link-label">Collapse</span>
        </button>
      </div>
    </aside>
  )
}
