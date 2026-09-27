import type { ReactNode } from 'react'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import './Alert.css'

type AlertTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

const ICONS: Record<AlertTone, IconName> = {
  info: 'info', success: 'checkCircle', warning: 'alert', danger: 'xCircle', neutral: 'info',
}

interface AlertProps {
  tone?: AlertTone
  title?: ReactNode
  children?: ReactNode
  action?: ReactNode
  onDismiss?: () => void
}

/** Inline, persistent message. Danger/warning alerts are announced to assistive technology. */
export function Alert({ tone = 'info', title, children, action, onDismiss }: AlertProps) {
  const urgent = tone === 'danger' || tone === 'warning'
  return (
    <div className={`alert alert--${tone}`} role={urgent ? 'alert' : 'status'}>
      <Icon name={ICONS[tone]} size={18} className="alert__icon" />
      <div className="alert__content">
        {title ? <p className="alert__title">{title}</p> : null}
        {children ? <div className="alert__body">{children}</div> : null}
      </div>
      {action ? <div className="alert__action">{action}</div> : null}
      {onDismiss ? (
        <button type="button" className="alert__dismiss" onClick={onDismiss} aria-label="Dismiss message">
          <Icon name="close" size={16} />
        </button>
      ) : null}
    </div>
  )
}
