/** Shared behaviour for modal overlays: focus trap, Escape to close, focus restore, background scroll lock. */
import { useEffect, useLayoutEffect, useRef } from 'react'
import type { RefObject } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function useOverlay(open: boolean, onClose: () => void, panelRef: RefObject<HTMLElement | null>,
  options: { closeOnEscape?: boolean } = {}) {
  const closeOnEscape = options.closeOnEscape ?? true
  const onCloseRef = useRef(onClose)
  useLayoutEffect(() => { onCloseRef.current = onClose })

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') ?? focusables()[0] ?? panel
    initial?.focus()

    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && closeOnEscape) {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = originalOverflow
      previouslyFocused?.focus?.()
    }
  }, [open, panelRef, closeOnEscape])
}

/** Close a popover on outside click or Escape. */
export function useDismiss(open: boolean, onClose: () => void, ref: RefObject<HTMLElement | null>) {
  const onCloseRef = useRef(onClose)
  useLayoutEffect(() => { onCloseRef.current = onClose })
  useEffect(() => {
    if (!open) return
    function onPointer(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) onCloseRef.current()
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, ref])
}
