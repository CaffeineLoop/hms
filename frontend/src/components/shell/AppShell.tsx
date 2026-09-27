/** The persistent HMS application shell: sidebar, top header and the main content region. */
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { systemApi } from '../../api/endpoints'
import { useQuery } from '../../hooks/useQuery'
import { IconButton } from '../ui'
import { Sidebar } from './Sidebar'
import { NotificationsMenu, UserMenu } from './TopbarMenus'
import './AppShell.css'

const COLLAPSE_KEY = 'hms.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  const health = useQuery((signal) => systemApi.health(signal), [])
  const environment = health.data?.environment

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [collapsed])

  return (
    <div className={['shell', collapsed ? 'shell--collapsed' : ''].join(' ')}>
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar collapsed={collapsed} mobileOpen={mobileOpen} onNavigate={() => setMobileOpen(false)}
        onToggleCollapsed={() => setCollapsed((v) => !v)} />
      {mobileOpen ? <div className="shell__scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" /> : null}

      <div className="shell__main">
        <header className="topbar">
          <IconButton icon="menu" label="Open navigation" className="topbar__menu" onClick={() => setMobileOpen(true)} />
          <div className="topbar__context">
            <span className="topbar__facility">Hospital Management System</span>
            {environment && environment !== 'production' ? (
              <span className="env-pill" title="Non-production environment: data is synthetic test/demo data">
                <span className="env-pill__dot" aria-hidden="true" />
                {environment.charAt(0).toUpperCase() + environment.slice(1)} environment · synthetic data
              </span>
            ) : null}
          </div>
          <div className="topbar__actions">
            <NotificationsMenu />
            <span className="topbar__divider" aria-hidden="true" />
            <UserMenu />
          </div>
        </header>

        <main id="main" className="content" tabIndex={-1}>
          <div className="content__inner">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
