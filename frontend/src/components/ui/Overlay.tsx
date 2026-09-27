/** Modal, Drawer and ConfirmDialog — accessible dialogs rendered in a portal. */
import { useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useOverlay } from '../../hooks/useOverlay'
import { Button } from './Button'
import { IconButton } from './Button'
import { Input } from './Field'
import './Overlay.css'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  /** Prevent accidental dismissal (e.g. unsaved clinical data): no overlay-click close. */
  dismissible?: boolean
}

export function Modal({ open, onClose, title, description, children, footer, size = 'md', dismissible = true }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descId = useId()
  useOverlay(open, onClose, panelRef, { closeOnEscape: dismissible })
  if (!open) return null
  return createPortal(
    <div className="overlay overlay--center" onMouseDown={(e) => { if (dismissible && e.target === e.currentTarget) onClose() }}>
      <div ref={panelRef} className={`dialog dialog--${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined} tabIndex={-1}>
        <header className="dialog__header">
          <div>
            <h2 className="dialog__title" id={titleId}>{title}</h2>
            {description ? <p className="dialog__description" id={descId}>{description}</p> : null}
          </div>
          <IconButton icon="close" label="Close dialog" size="sm" onClick={onClose} />
        </header>
        {children ? <div className="dialog__body">{children}</div> : null}
        {footer ? <footer className="dialog__footer">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  )
}

export function Drawer({ open, onClose, title, description, children, footer, size = 'md' }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useOverlay(open, onClose, panelRef)
  if (!open) return null
  return createPortal(
    <div className="overlay overlay--right" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <aside ref={panelRef} className={`drawer drawer--${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="drawer__header">
          <div>
            <h2 className="dialog__title" id={titleId}>{title}</h2>
            {description ? <p className="dialog__description">{description}</p> : null}
          </div>
          <IconButton icon="close" label="Close panel" size="sm" onClick={onClose} />
        </header>
        <div className="drawer__body">{children}</div>
        {footer ? <footer className="dialog__footer">{footer}</footer> : null}
      </aside>
    </div>,
    document.body,
  )
}

interface ConfirmDialogProps {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
  title: string
  children: ReactNode
  confirmLabel: string
  tone?: 'danger' | 'primary'
  /** For irreversible actions: the user must type this text (e.g. the Patient ID) to enable confirmation. */
  confirmationText?: string
  busy?: boolean
}

/** Safe confirmation for consequential actions. The safe choice (Cancel) receives initial focus. */
export function ConfirmDialog({ open, onCancel, onConfirm, title, children, confirmLabel, tone = 'danger',
  confirmationText, busy }: ConfirmDialogProps) {
  const [typed, setTyped] = useState('')
  const matches = !confirmationText || typed.trim() === confirmationText
  const close = () => { setTyped(''); onCancel() }
  return (
    <Modal open={open} onClose={close} title={title} size="sm" dismissible={!busy}
      footer={<>
        <Button variant="secondary" onClick={close} disabled={busy} data-autofocus>Cancel</Button>
        <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} disabled={!matches} loading={busy}>
          {confirmLabel}
        </Button>
      </>}>
      <div className="stack">
        <div className="dialog__text">{children}</div>
        {confirmationText ? (
          <label className="confirm-type">
            <span>Type <strong className="mono">{confirmationText}</strong> to confirm</span>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
          </label>
        ) : null}
      </div>
    </Modal>
  )
}
