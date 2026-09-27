/**
 * Provenance: every piece of clinical information shows WHERE it comes from.
 *
 *   record  a documented clinical record (entered and attributed to staff) — solid, authoritative
 *   system  a system/workflow status (computed or process state) — quiet, informational
 *   ai      an AI-generated suggestion — distinct violet with a dashed edge and an explicit
 *           "requires clinician review" notice; it must never look like a confirmed diagnosis or record.
 */
import type { ReactNode } from 'react'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import './Provenance.css'

export type ProvenanceKind = 'record' | 'system' | 'ai'

const META: Record<ProvenanceKind, { label: string; icon: IconName }> = {
  record: { label: 'Documented record', icon: 'document' },
  system: { label: 'System status', icon: 'settings' },
  ai: { label: 'AI suggestion', icon: 'ai' },
}

export function ProvenanceTag({ kind, children }: { kind: ProvenanceKind; children?: ReactNode }) {
  return (
    <span className={`prov-tag prov-tag--${kind}`}>
      <Icon name={META[kind].icon} size={13} />
      {children ?? META[kind].label}
    </span>
  )
}

interface ProvenancePanelProps {
  kind: ProvenanceKind
  title: ReactNode
  meta?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

/** A block of clinical content framed by its provenance. AI panels always carry the review notice. */
export function ProvenancePanel({ kind, title, meta, children, footer }: ProvenancePanelProps) {
  return (
    <section className={`prov-panel prov-panel--${kind}`} aria-label={`${META[kind].label}: ${typeof title === 'string' ? title : ''}`}>
      <header className="prov-panel__header">
        <ProvenanceTag kind={kind} />
        <h3 className="prov-panel__title">{title}</h3>
        {meta ? <div className="prov-panel__meta">{meta}</div> : null}
      </header>
      <div className="prov-panel__body">{children}</div>
      {kind === 'ai' ? (
        <p className="prov-panel__notice">
          <Icon name="info" size={14} />
          Suggestion for clinical review only — not a diagnosis, order or treatment decision. Requires clinician review.
        </p>
      ) : null}
      {footer ? <footer className="prov-panel__footer">{footer}</footer> : null}
    </section>
  )
}
