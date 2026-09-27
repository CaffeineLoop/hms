/**
 * Vitals & observations (GET /patients/{id}/observations: code, encounter_id, paging; newest first).
 * Values are shown as recorded, in conventional units. Blood pressure pairs (systolic + diastolic sharing the same
 * time) are shown as one "120/80 mmHg" reading. No normal/abnormal interpretation is added.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { clinicalApi } from '../../../api/endpoints'
import { useAuth } from '../../../auth/useAuth'
import type { Column } from '../../../components/ui'
import { Card, DataTable, EmptyState, ErrorState, Field, LinkButton, LoadingState, Pagination, Select } from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import type { VitalRow } from '../../../lib/clinical'
import { bloodPressureValue, latestVitals, OBSERVATION_CODES, observationValue, pairBloodPressure, VITAL_ORDER } from '../../../lib/clinical'
import { formatDateTime, formatShortDateTime } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { SectionHead } from '../shared'
import { SavedNotice } from '../writes/ClinicalForms'

const PAGE_SIZE = 50

function rowTime(row: VitalRow) {
  return row.kind === 'bp' ? row.systolic.effective_at : row.observation.effective_at
}

export function VitalsSection() {
  const { patient } = usePatientRecord()
  const { canReadClinical, hasAllScope } = useAuth()
  const [code, setCode] = useState('')
  const [offset, setOffset] = useState(0)
  const latest = useQuery((s) => clinicalApi.observations(patient.id, { limit: 100 }, s), [patient.id])
  const list = useQuery((s) => clinicalApi.observations(patient.id, { code: code || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, code, offset])

  const tiles = latest.data ? latestVitals(latest.data.items) : []
  const rank = (row: VitalRow) => {
    const index = VITAL_ORDER.indexOf(row.kind === 'bp' ? 'blood_pressure' : row.observation.code)
    return index === -1 ? VITAL_ORDER.length : index
  }
  tiles.sort((a, b) => rank(a) - rank(b))
  const rows = list.data ? pairBloodPressure(list.data.items) : undefined

  const columns: Column<VitalRow>[] = [
    { key: 'when', header: 'Recorded', numeric: true, width: 190, render: (r) => <span className="cell-strong">{formatDateTime(rowTime(r))}</span> },
    { key: 'what', header: 'Measurement', render: (r) => (
      <span className="cell-stack">
        <span>{r.kind === 'bp' ? 'Blood pressure (systolic/diastolic)' : r.observation.display}</span>
        {r.kind === 'single' && r.observation.notes ? <span className="cell-sub">{r.observation.notes}</span> : null}
      </span>) },
    { key: 'value', header: 'Value', align: 'right', numeric: true,
      render: (r) => <span className="value-strong">{r.kind === 'bp' ? bloodPressureValue(r.systolic, r.diastolic) : observationValue(r.observation)}</span> },
    { key: 'coding', header: 'Code', priority: 'tertiary', render: (r) => {
      const o = r.kind === 'bp' ? null : r.observation
      return o?.system_code ? <span className="mono text-muted">LOINC {o.system_code}</span> : <span className="text-subtle">—</span>
    } },
    { key: 'encounter', header: 'Encounter', priority: 'secondary', render: (r) => {
      const encounterId = r.kind === 'bp' ? r.systolic.encounter_id : r.observation.encounter_id
      return encounterId && canReadClinical('encounter.view')
        ? <Link to={`/patients/${patient.id}/encounters/${encounterId}`} onClick={(e) => e.stopPropagation()}>View</Link>
        : <span className="text-subtle">—</span>
    } },
  ]

  return (
    <>
      <SavedNotice />
      <SectionHead title="Vitals & observations" meta={<span>Values exactly as recorded</span>}>
        {hasAllScope('observation.create') ? <LinkButton to="new" variant="primary" icon="plus">Record vitals</LinkButton> : null}
        <Field label="Measurement">
          <Select value={code} onChange={(e) => { setCode(e.target.value); setOffset(0) }}>
            <option value="">All measurements</option>
            {OBSERVATION_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
          </Select>
        </Field>
      </SectionHead>

      {latest.error ? null : latest.loading ? <LoadingState label="Loading latest vitals…" /> : tiles.length > 0 ? (
        <section aria-label="Latest values" className="vitals-grid" style={{ marginBottom: 'var(--space-5)' }}>
          {tiles.map((row) => (
            <div className="vital" key={row.key}>
              <span className="vital__label">{row.kind === 'bp' ? 'Blood pressure' : row.observation.display}</span>
              <span className="vital__value tabular">{row.kind === 'bp' ? bloodPressureValue(row.systolic, row.diastolic) : observationValue(row.observation)}</span>
              <span className="vital__time">Latest · {formatShortDateTime(rowTime(row))}</span>
            </div>
          ))}
        </section>
      ) : null}

      <Card padding="none" title={code ? OBSERVATION_CODES.find((c) => c.code === code)?.label : 'All observations'}
        description="Newest first">
        {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : (
          <>
            <DataTable caption="Observations" columns={columns} rows={rows} rowKey={(r) => r.key} loading={list.loading && !list.data}
              empty={<EmptyState icon="pulse" title={code ? 'No readings of this measurement' : 'No observations recorded'} />} />
            {list.data ? <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="readings" /> : null}
          </>
        )}
      </Card>
    </>
  )
}
