/** Header menus: notifications (derived from real HMS data) and the signed-in user's account menu. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { aiApi, workflowApi } from '../../api/endpoints'
import { useAuth } from '../../auth/useAuth'
import { useQuery } from '../../hooks/useQuery'
import { humanize } from '../../lib/format'
import { Icon } from '../icons/Icon'
import { Avatar, IconButton, Popover } from '../ui'

interface Notice {
  id: string
  tone: 'ai' | 'warning'
  title: string
  detail: string
  to: string
}

export function NotificationsMenu() {
  const { can, canAny } = useAuth()
  const [open, setOpen] = useState(false)
  const reviewEnabled = canAny('ai.analysis', 'ai.review')
  const tasksEnabled = can('workflow.view')
  const reviews = useQuery((signal) => aiApi.riskAnalyses({ review_status: 'PENDING_REVIEW', limit: 1 }, signal), [],
    { enabled: reviewEnabled })
  const urgent = useQuery((signal) => workflowApi.tasks({ priority: 'URGENT', status: 'OPEN', limit: 1 }, signal), [],
    { enabled: tasksEnabled })

  const notices: Notice[] = []
  if (reviews.data && reviews.data.total > 0) {
    notices.push({ id: 'ai', tone: 'ai', title: `${reviews.data.total} AI suggestion${reviews.data.total === 1 ? '' : 's'} awaiting review`,
      detail: 'Four-day potential risk analyses pending clinician review.', to: '/ai' })
  }
  if (urgent.data && urgent.data.total > 0) {
    notices.push({ id: 'urgent', tone: 'warning', title: `${urgent.data.total} urgent open task${urgent.data.total === 1 ? '' : 's'}`,
      detail: 'Unassigned workflow tasks marked urgent.', to: '/workflows/tasks' })
  }

  return (
    <Popover open={open} onClose={() => setOpen(false)} label="Notifications" width={340}
      trigger={<IconButton icon="bell" label={`Notifications${notices.length ? ` (${notices.length})` : ''}`}
        badge={notices.length} onClick={() => setOpen((v) => !v)} aria-expanded={open} />}>
      <div className="notif">
        <div className="notif__header">
          <span className="notif__title">Notifications</span>
          <span className="notif__source">Live from HMS</span>
        </div>
        {notices.length === 0 ? (
          <p className="notif__empty">You're all caught up.</p>
        ) : (
          <ul className="notif__list">
            {notices.map((n) => (
              <li key={n.id}>
                <Link to={n.to} className={`notif__item notif__item--${n.tone}`} onClick={() => setOpen(false)}>
                  <span className="notif__icon"><Icon name={n.tone === 'ai' ? 'ai' : 'alert'} size={16} /></span>
                  <span>
                    <span className="notif__item-title">{n.title}</span>
                    <span className="notif__item-detail">{n.detail}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Popover>
  )
}

export function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  if (!user) return null
  const name = user.staff.full_name
  return (
    <Popover open={open} onClose={() => setOpen(false)} label="Account" width={280}
      trigger={
        <button type="button" className="user-trigger" onClick={() => setOpen((v) => !v)} aria-expanded={open}
          aria-haspopup="dialog">
          <Avatar name={name} size={32} />
          <span className="user-trigger__text">
            <span className="user-trigger__name">{name}</span>
            <span className="user-trigger__role">{humanize(user.staff.designation)}</span>
          </span>
          <Icon name="chevronDown" size={16} className="user-trigger__chevron" />
        </button>
      }>
      <div className="account">
        <div className="account__who">
          <Avatar name={name} size={40} />
          <div>
            <p className="account__name">{name}</p>
            <p className="account__meta">{user.username} · {user.staff.employee_code}</p>
          </div>
        </div>
        <div className="account__roles">
          {(user.is_superuser ? ['Super administrator'] : user.roles.map(humanize)).map((role) => (
            <span className="account__role" key={role}>{role}</span>
          ))}
        </div>
        <div className="menu">
          <Link to="/account" className="menu__item" onClick={() => setOpen(false)}>
            <Icon name="user" size={16} /> My account
          </Link>
          <button type="button" className="menu__item menu__item--danger" onClick={() => { setOpen(false); void logout() }}>
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      </div>
    </Popover>
  )
}
