/**
 * Clinical presentation rules — formatting only. Values are shown exactly as recorded by the HMS; the UI never
 * derives interpretations (no normal/abnormal flags, no ranges, no diagnoses).
 */
import type { IconName } from '../components/icons/Icon'
import type { ProvenanceKind } from '../components/ui'
import type { LabResult, Observation, PrescriptionItem, ResultInterpretation, TimelineEvent, TimelineEventType } from '../api/types'

/** UCUM units as stored by the HMS (observation catalog) -> conventional clinical symbols. */
const UNIT_SYMBOLS: Record<string, string> = {
  Cel: '°C', '[degF]': '°F', 'mm[Hg]': 'mmHg', '/min': '/min', '%': '%', kg: 'kg', cm: 'cm', '[lb_av]': 'lb',
  'mg/dL': 'mg/dL', 'mmol/L': 'mmol/L',
  // laboratory UCUM units
  '10*3/uL': '×10³/µL', '10*6/uL': '×10⁶/µL', '10*9/L': '×10⁹/L', '10*12/L': '×10¹²/L', 'u[IU]/mL': 'µIU/mL',
  'ug/L': 'µg/L', 'umol/L': 'µmol/L', 'fL': 'fL', 'pg': 'pg',
}

export function unitSymbol(unit: string | null | undefined): string {
  if (!unit) return ''
  return UNIT_SYMBOLS[unit] ?? unit
}

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

/** "38.9 °C", "92 %", or the recorded text value. */
export function observationValue(o: Pick<Observation, 'value_numeric' | 'value_text' | 'unit'>): string {
  if (o.value_numeric !== null && o.value_numeric !== undefined) {
    const symbol = unitSymbol(o.unit)
    const value = numberFormat.format(o.value_numeric)
    if (!symbol) return value
    return symbol === '%' ? `${value}%` : `${value} ${symbol}`
  }
  return o.value_text ?? '—'
}

export const SYSTOLIC = 'systolic_blood_pressure'
export const DIASTOLIC = 'diastolic_blood_pressure'

export type VitalRow =
  | { kind: 'single'; key: string; observation: Observation }
  | { kind: 'bp'; key: string; systolic: Observation; diastolic: Observation }

/**
 * Pair systolic + diastolic readings recorded at the same instant (and encounter) into one blood-pressure row,
 * the way the HMS stores them (two observations sharing effective_at). Unpaired halves stay separate rows.
 */
export function pairBloodPressure(observations: Observation[]): VitalRow[] {
  const diastolicByKey = new Map<string, Observation>()
  for (const o of observations) {
    if (o.code === DIASTOLIC) diastolicByKey.set(`${o.effective_at}|${o.encounter_id ?? ''}`, o)
  }
  const used = new Set<string>()
  const rows: VitalRow[] = []
  for (const o of observations) {
    if (o.code === SYSTOLIC) {
      const pairKey = `${o.effective_at}|${o.encounter_id ?? ''}`
      const diastolic = diastolicByKey.get(pairKey)
      if (diastolic && !used.has(diastolic.id)) {
        used.add(diastolic.id)
        rows.push({ kind: 'bp', key: `${o.id}+${diastolic.id}`, systolic: o, diastolic })
        continue
      }
    }
    if (o.code === DIASTOLIC && used.has(o.id)) continue
    rows.push({ kind: 'single', key: o.id, observation: o })
  }
  // a diastolic listed before its systolic partner was already consumed above; drop its duplicate single row
  return rows.filter((row) => row.kind === 'bp' || !used.has(row.observation.id))
}

export function bloodPressureValue(systolic: Observation, diastolic: Observation): string {
  const unit = unitSymbol(systolic.unit) || unitSymbol(diastolic.unit)
  return `${numberFormat.format(systolic.value_numeric ?? 0)}/${numberFormat.format(diastolic.value_numeric ?? 0)}${unit ? ` ${unit}` : ''}`
}

/** Most recent reading per vital sign (input sorted newest first, as the API returns it). */
export function latestVitals(observations: Observation[]): VitalRow[] {
  const seen = new Set<string>()
  const latest: VitalRow[] = []
  for (const row of pairBloodPressure(observations)) {
    const code = row.kind === 'bp' ? 'blood_pressure' : row.observation.code
    if (seen.has(code)) continue
    if (row.kind === 'single' && (row.observation.code === SYSTOLIC || row.observation.code === DIASTOLIC) && seen.has('blood_pressure')) continue
    seen.add(code)
    latest.push(row)
  }
  return latest
}

export const VITAL_ORDER = ['blood_pressure', 'heart_rate', 'respiratory_rate', 'oxygen_saturation', 'body_temperature',
  'blood_glucose', 'body_weight', 'body_height']

export const OBSERVATION_CODES: Array<{ code: string; label: string }> = [
  { code: 'heart_rate', label: 'Heart rate' },
  { code: 'respiratory_rate', label: 'Respiratory rate' },
  { code: 'oxygen_saturation', label: 'Oxygen saturation (SpO₂)' },
  { code: 'body_temperature', label: 'Body temperature' },
  { code: SYSTOLIC, label: 'Systolic blood pressure' },
  { code: DIASTOLIC, label: 'Diastolic blood pressure' },
  { code: 'blood_glucose', label: 'Blood glucose' },
  { code: 'body_weight', label: 'Body weight' },
  { code: 'body_height', label: 'Body height' },
]

// ---------------------------------------------------------------- timeline

interface EventMeta {
  label: string
  icon: IconName
  provenance: ProvenanceKind
}

/**
 * Clinical documentation (entered and attributed by clinicians) is a `record`; scheduling and process tracking
 * is `system`. AI output is never part of the timeline (it is stored separately for review).
 */
export const TIMELINE_TYPES: Record<TimelineEventType, EventMeta> = {
  encounter: { label: 'Encounter', icon: 'clinical', provenance: 'record' },
  observation: { label: 'Observation', icon: 'pulse', provenance: 'record' },
  condition: { label: 'Condition', icon: 'document', provenance: 'record' },
  allergy: { label: 'Allergy', icon: 'alert', provenance: 'record' },
  clinical_note: { label: 'Clinical note', icon: 'edit', provenance: 'record' },
  lab_order: { label: 'Lab order', icon: 'diagnostics', provenance: 'record' },
  lab_sample: { label: 'Lab sample', icon: 'diagnostics', provenance: 'system' },
  lab_result: { label: 'Lab result', icon: 'diagnostics', provenance: 'record' },
  report: { label: 'Report', icon: 'document', provenance: 'record' },
  prescription: { label: 'Prescription', icon: 'prescriptions', provenance: 'record' },
  appointment: { label: 'Appointment', icon: 'calendar', provenance: 'system' },
  admission: { label: 'Admission', icon: 'bed', provenance: 'record' },
  admission_transfer: { label: 'Transfer', icon: 'bed', provenance: 'record' },
  workflow_task: { label: 'Workflow task', icon: 'workflows', provenance: 'system' },
}

/** Types offered as timeline filters (the modules the UI delivers); others still appear in "All". */
export const TIMELINE_FILTER_TYPES: TimelineEventType[] = ['encounter', 'observation', 'condition', 'allergy', 'clinical_note',
  'lab_order', 'lab_result', 'report', 'prescription']

const ATTRIBUTION_FIELDS: Array<[string, string]> = [
  ['author_name', 'Authored by'], ['prescriber_name', 'Prescribed by'], ['ordered_by', 'Ordered by'],
  ['entered_by', 'Entered by'], ['collected_by', 'Collected by'], ['verified_by', 'Verified by'],
]

/** Attribution exactly as recorded in the event's underlying record (never inferred). */
export function eventAttribution(event: TimelineEvent): string | null {
  for (const [field, label] of ATTRIBUTION_FIELDS) {
    const value = event.data[field]
    if (typeof value === 'string' && value.trim()) return `${label} ${value}`
  }
  return null
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

/** One-line clinical detail for an event, built only from fields present in the record. */
export function eventDetail(event: TimelineEvent): string | null {
  const d = event.data
  switch (event.event_type) {
    case 'observation':
      return observationValue({
        value_numeric: typeof d.value_numeric === 'number' ? d.value_numeric : null,
        value_text: text(d.value_text), unit: text(d.unit),
      })
    case 'encounter':
      return text(d.reason)
    case 'allergy':
      return [text(d.reaction), text(d.severity) ? `Severity: ${String(d.severity).toLowerCase()}` : null].filter(Boolean).join(' · ') || null
    case 'clinical_note': {
      const content = text(d.content)
      return content ? (content.length > 180 ? `${content.slice(0, 180).trimEnd()}…` : content) : null
    }
    case 'condition':
      return text(d.notes)
    case 'lab_order':
      return text(d.clinical_indication) ? `Indication: ${d.clinical_indication}` : null
    case 'report':
      return text(d.conclusion)
    default:
      return null
  }
}

/** Headline for a timeline card, from the record's own fields (observations: recorded name; encounters: type). */
export function eventHeadline(event: TimelineEvent): string {
  const d = event.data
  if (event.event_type === 'observation' && typeof d.display === 'string') return d.display
  if (event.event_type === 'encounter' && typeof d.encounter_type === 'string') {
    const type = d.encounter_type.replace(/_/g, ' ').toLowerCase()
    return `${type.charAt(0).toUpperCase()}${type.slice(1)} encounter`
  }
  return event.title
}

export type TimelineItem =
  | { kind: 'event'; key: string; event: TimelineEvent }
  | { kind: 'bp'; key: string; systolic: TimelineEvent; diastolic: TimelineEvent }

function asObservation(event: TimelineEvent): Observation {
  const d = event.data
  return {
    id: event.record_id, patient_id: String(d.patient_id ?? ''), encounter_id: event.encounter_id, code: String(d.code ?? ''),
    display: String(d.display ?? ''), code_system: null, system_code: null,
    value_numeric: typeof d.value_numeric === 'number' ? d.value_numeric : null,
    value_text: typeof d.value_text === 'string' ? d.value_text : null, unit: typeof d.unit === 'string' ? d.unit : null,
    effective_at: event.occurred_at, notes: null, created_at: event.occurred_at,
  }
}

/** Merge systolic + diastolic observation events recorded at the same instant (and encounter) into one BP item. */
export function pairTimelineBloodPressure(events: TimelineEvent[]): TimelineItem[] {
  const observations = events.filter((e) => e.event_type === 'observation').map(asObservation)
  const pairs = pairBloodPressure(observations).filter((row) => row.kind === 'bp')
  const pairedBy = new Map<string, { systolicId: string; diastolicId: string }>()
  for (const row of pairs) {
    if (row.kind === 'bp') {
      pairedBy.set(row.systolic.id, { systolicId: row.systolic.id, diastolicId: row.diastolic.id })
      pairedBy.set(row.diastolic.id, { systolicId: row.systolic.id, diastolicId: row.diastolic.id })
    }
  }
  const byId = new Map(events.map((e) => [e.record_id, e]))
  const items: TimelineItem[] = []
  const emitted = new Set<string>()
  for (const event of events) {
    const pair = event.event_type === 'observation' ? pairedBy.get(event.record_id) : undefined
    if (!pair) {
      items.push({ kind: 'event', key: `${event.event_type}-${event.record_id}`, event })
      continue
    }
    if (emitted.has(pair.systolicId)) continue
    emitted.add(pair.systolicId)
    items.push({ kind: 'bp', key: `bp-${pair.systolicId}`, systolic: byId.get(pair.systolicId)!, diastolic: byId.get(pair.diastolicId)! })
  }
  return items
}

export function timelineBloodPressureValue(systolic: TimelineEvent, diastolic: TimelineEvent): string {
  return bloodPressureValue(asObservation(systolic), asObservation(diastolic))
}

/**
 * Where a timeline event opens in the record (UI-2 detail views), with the permission the backend requires for that
 * read. Samples and results open their lab order, which shows them in context.
 */
function localDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function eventRecordLink(event: TimelineEvent, patientId: string): { to: string; label: string; permission: string } | null {
  const base = `/patients/${patientId}`
  const orderId = typeof event.data.lab_order_id === 'string' ? event.data.lab_order_id : null
  switch (event.event_type) {
    case 'lab_order':
      return { to: `${base}/diagnostics/lab-orders/${event.record_id}`, label: 'Open lab order', permission: 'lab.view' }
    case 'lab_sample':
    case 'lab_result':
      return orderId ? { to: `${base}/diagnostics/lab-orders/${orderId}`, label: 'Open lab order', permission: 'lab.view' } : null
    case 'report':
      return { to: `${base}/diagnostics/reports/${event.record_id}`, label: 'Open report', permission: 'report.view' }
    case 'prescription':
      return { to: `${base}/prescriptions/${event.record_id}`, label: 'Open prescription', permission: 'prescription.view' }
    // UI-6: workflow events open their workflow list (appointments on the day they are scheduled)
    case 'appointment':
      return { to: `/workflows/appointments?date=${localDay(event.occurred_at)}`, label: 'Open appointments', permission: 'appointment.view' }
    case 'admission':
    case 'admission_transfer':
      return { to: '/workflows/admissions', label: 'Open admissions', permission: 'admission.view' }
    case 'workflow_task':
      return { to: '/workflows/tasks', label: 'Open tasks', permission: 'workflow.view' }
    default:
      return null
  }
}

// ---------------------------------------------------------------- diagnostics & prescriptions

/** A lab result value exactly as entered ("9.2 g/dL" or the recorded text). */
export function labResultValue(r: Pick<LabResult, 'value_numeric' | 'value_text' | 'unit'>): string {
  return observationValue(r)
}

/** The reference range as recorded with the result ("12–16 g/dL", "< 5", or the recorded text). */
export function labReferenceRange(r: LabResult): string | null {
  const unit = unitSymbol(r.unit)
  const suffix = unit ? ` ${unit}` : ''
  if (r.reference_low !== null && r.reference_high !== null) {
    return `${numberFormat.format(r.reference_low)}–${numberFormat.format(r.reference_high)}${suffix}`
  }
  if (r.reference_low !== null) return `≥ ${numberFormat.format(r.reference_low)}${suffix}`
  if (r.reference_high !== null) return `≤ ${numberFormat.format(r.reference_high)}${suffix}`
  return r.reference_text
}

/** The laboratory's recorded flag (stored with the result by the HMS) — shown, never computed by the UI. */
export const INTERPRETATION_LABEL: Record<ResultInterpretation, string> = {
  NORMAL: 'Normal', LOW: 'Low', HIGH: 'High', CRITICAL_LOW: 'Critical low', CRITICAL_HIGH: 'Critical high', ABNORMAL: 'Abnormal',
}
export const INTERPRETATION_TONE: Record<ResultInterpretation, 'neutral' | 'warning' | 'danger'> = {
  NORMAL: 'neutral', LOW: 'warning', HIGH: 'warning', ABNORMAL: 'warning', CRITICAL_LOW: 'danger', CRITICAL_HIGH: 'danger',
}

/** Lab order lifecycle, in the order the backend allows (cancellation can end it at any open step). */
export const LAB_ORDER_STEPS = [
  { status: 'ORDERED', label: 'Ordered', at: 'ordered_at' },
  { status: 'SAMPLE_COLLECTED', label: 'Sample collected', at: null },
  { status: 'PROCESSING', label: 'Processing', at: 'processing_started_at' },
  { status: 'RESULT_ENTERED', label: 'Results entered', at: 'results_entered_at' },
  { status: 'VERIFIED', label: 'Verified', at: 'verified_at' },
  { status: 'RELEASED', label: 'Released', at: 'released_at' },
] as const

export const FREQUENCY_LABEL: Record<string, string> = {
  ONCE: 'Once', STAT: 'Immediately (STAT)', OD: 'Once daily', BID: 'Twice daily', TID: 'Three times daily',
  QID: 'Four times daily', Q4H: 'Every 4 hours', Q6H: 'Every 6 hours', Q8H: 'Every 8 hours', Q12H: 'Every 12 hours',
  NOCTE: 'At night', WEEKLY: 'Weekly', PRN: 'As needed (PRN)',
}

/** Doses are written without digit grouping ("1000 mg", never "1,000 mg"), as in prescribing practice. */
const doseFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3, useGrouping: false })

/** "500 mg" — the dose exactly as prescribed. */
export function prescriptionDose(item: PrescriptionItem): string {
  return `${doseFormat.format(item.dose_value)} ${item.dose_unit}`
}

/** "7 days" / null. */
export function prescriptionDuration(item: PrescriptionItem): string | null {
  if (item.duration_value === null || !item.duration_unit) return null
  const unit = item.duration_unit.toLowerCase()
  return `${item.duration_value} ${item.duration_value === 1 ? unit.replace(/s$/, '') : unit}`
}

/** "21 capsule" / null. */
export function prescriptionQuantity(item: PrescriptionItem): string | null {
  if (item.quantity === null) return null
  return `${numberFormat.format(item.quantity)}${item.quantity_unit ? ` ${item.quantity_unit}` : ''}`
}

/** Terminology label for a recorded code system URI. */
export function codingLabel(system: string | null): string {
  if (!system) return 'Code'
  if (system.includes('snomed')) return 'SNOMED CT'
  if (system.includes('rxnorm')) return 'RxNorm'
  if (system.includes('loinc')) return 'LOINC'
  return system
}
