/** Anchored popover used for header menus (notifications, account). Closes on outside click / Escape. */
import { useRef } from 'react'
import type { ReactNode } from 'react'
import { useDismiss } from '../../hooks/useOverlay'
import './Popover.css'

interface PopoverProps {
  open: boolean
  onClose: () => void
  trigger: ReactNode
  children: ReactNode
  align?: 'start' | 'end'
  width?: number
  label: string
}

export function Popover({ open, onClose, trigger, children, align = 'end', width = 320, label }: PopoverProps) {
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(open, onClose, ref)
  return (
    <div className="popover" ref={ref}>
      {trigger}
      {open ? (
        <div className={`popover__panel popover__panel--${align}`} style={{ width }} role="dialog" aria-label={label}>
          {children}
        </div>
      ) : null}
    </div>
  )
}
