/**
 * Patient timeline (GET /api/patients/{id}/timeline). The backend already limits event types to what the user may
 * see; the UI shows what it returns. Documented records and system/workflow events are styled differently, and AI
 * output never appears here (AI analyses are stored separately for clinician review).
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { clinicalApi } from '../../../api/endpoints'
import type { TimelineEvent, TimelineEventType } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import { Icon } from '../../../components/icons/Icon'
import { Card, EmptyState, ErrorState, LoadingState, Pagination, ProvenanceTag, StatusBadge } from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import type { TimelineItem as Item } from '../../../lib/clinical'
import {
  eventAttribution, eventDetail, eventHeadline, eventRecordLink, pairTimelineBloodPressure, TIMELINE_FILTER_TYPES, TIMELINE_TYPES,
  timelineBloodPressureValue,
} from '../../../lib/clinical'
import { formatTime } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { SectionHead } from '../shared'

const PAGE_SIZE = 25
const dayFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

export function TimelineSection() {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  const [types, setTypes] = useState<TimelineEventType[]>([])
  const [order, setOrder] = useState<'desc' | 'asc'>('desc')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => clinicalApi.timeline(patient.id, { types, order, limit: PAGE_SIZE, offset }, s),
    [patient.id, types, order, offset])

  function toggle(type: TimelineEventType) {
    setOffset(0)
    setTypes((current) => (current.includes(type) ? current.filter((t) => t !== type) : [...current, type]))
  }

  const groups: Array<{ key: string; label: string; events: TimelineEvent[]; items?: Item[] }> = []
  for (const event of result.data?.items ?? []) {
    const key = dayKey(event.occurred_at)
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.events.push(event)
    else groups.push({ key, label: dayFormat.format(new Date(event.occurred_at)), events: [event] })
  }
  for (const group of groups) group.items = pairTimelineBloodPressure(group.events)

  return (
    <>
      <SectionHead title="Clinical timeline"
        meta={<><span>solid edge</span><span aria-hidden="true">·</span><ProvenanceTag kind="system" /><span>scheduling and process events</span></>} />
      <div className="tl-toolbar">
        <div className="chips" role="group" aria-label="Filter by event type">
          <button type="button" className="chip" aria-pressed={types.length === 0} onClick={() => { setTypes([]); setOffset(0) }}>All events</button>
          {TIMELINE_FILTER_TYPES.map((type) => (
            <button key={type} type="button" className="chip" aria-pressed={types.includes(type)} onClick={() => toggle(type)}>
              <Icon name={TIMELINE_TYPES[type].icon} size={14} />{TIMELINE_TYPES[type].label}
            </button>
          ))}
        </div>
        <div className="chips" role="group" aria-label="Order">
          <button type="button" className="chip" aria-pressed={order === 'desc'} onClick={() => { setOrder('desc'); setOffset(0) }}>Newest first</button>
          <button type="button" className="chip" aria-pressed={order === 'asc'} onClick={() => { setOrder('asc'); setOffset(0) }}>Oldest first</button>
        </div>
      </div>

      {result.error ? <Card><ErrorState error={result.error} onRetry={result.reload} /></Card>
        : result.loading && !result.data ? <Card padding="none"><LoadingState rows={6} label="Loading timeline" /></Card>
          : groups.length === 0 ? (
            <Card><EmptyState icon="clock" title={types.length ? 'No events of the selected types' : 'No clinical history yet'}
              description={types.length ? 'Try a different filter.' : 'Events appear here as encounters, observations, conditions, allergies and notes are recorded.'} /></Card>
          ) : (
            <div aria-busy={result.loading || undefined}>
              {groups.map((group) => (
                <section key={group.key} className="tl-day" aria-label={group.label}>
                  <h3 className="tl-day__label">{group.label}</h3>
                  <ol className="tl-list">
                    {(group.items ?? []).map((item) => (
                      <TimelineItem key={item.key} item={item} patientId={patient.id} canRead={canReadClinical} />
                    ))}
                  </ol>
                </section>
              ))}
              {result.data ? (
                <Card padding="none">
                  <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="events" />
                </Card>
              ) : null}
            </div>
          )}
    </>
  )
}

function TimelineItem({ item, patientId, canRead }: { item: Item; patientId: string; canRead: (permission: string) => boolean }) {
  const event = item.kind === 'bp' ? item.systolic : item.event
  const meta = TIMELINE_TYPES[event.event_type]
  const headline = item.kind === 'bp' ? 'Blood pressure' : eventHeadline(event)
  const detail = item.kind === 'bp' ? timelineBloodPressureValue(item.systolic, item.diastolic) : eventDetail(event)
  const attribution = eventAttribution(event)
  const encounterId = event.event_type === 'encounter' ? event.record_id : event.encounter_id
  const canOpenEncounter = canRead('encounter.view')
  // UI-2: lab, report and prescription events open their detail view (only when the backend would allow the read).
  const recordLink = item.kind === 'event' ? eventRecordLink(event, patientId) : null
  const openRecord = recordLink && canRead(recordLink.permission) ? recordLink : null
  return (
    <li className={`tl-event tl-event--${meta.provenance}`}>
      <span className="tl-event__marker" aria-hidden="true"><Icon name={meta.icon} size={16} /></span>
      <article className="tl-card">
        <div className="tl-card__head">
          <span className="tl-card__type">{meta.label}</span>
          {meta.provenance !== 'record' ? <ProvenanceTag kind={meta.provenance} /> : null}
          {event.status ? <StatusBadge status={event.status} size="sm" /> : null}
          <time className="tl-card__time tabular" dateTime={event.occurred_at}>{formatTime(event.occurred_at)}</time>
        </div>
        <p className="tl-card__title">{headline}</p>
        {detail ? <p className={['tl-card__detail', event.event_type === 'observation' ? 'tl-card__detail--value tabular' : ''].join(' ')}>{detail}</p> : null}
        {attribution || openRecord || (encounterId && canOpenEncounter) ? (
          <div className="tl-card__foot">
            {attribution ? <span>{attribution}</span> : null}
            {openRecord ? <Link to={openRecord.to}>{openRecord.label}</Link> : null}
            {encounterId && canOpenEncounter ? (
              <Link to={`/patients/${patientId}/encounters/${encounterId}`}>
                {event.event_type === 'encounter' ? 'Open encounter' : 'View encounter'}
              </Link>
            ) : null}
          </div>
        ) : null}
      </article>
    </li>
  )
}
