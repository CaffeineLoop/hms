/**
 * UI-2 Prescriptions (read-only): GET /patients/{id}/prescriptions and /api/prescriptions/{id}.
 * Items are shown exactly as prescribed (dose, route, frequency, duration, quantity, instructions).
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { prescriptionsApi } from '../../../api/endpoints'
import type { Prescription, PrescriptionItem } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import type { Column } from '../../../components/ui'
import {
  Alert, Card, DataTable, DescriptionList, EmptyState, ErrorState, Field, LinkButton, Pagination, ProvenanceTag, Select,
  StatusBadge,
} from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import { codingLabel, FREQUENCY_LABEL, prescriptionDose, prescriptionDuration, prescriptionQuantity } from '../../../lib/clinical'
import { formatDateTime, humanize } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { Lifecycle, RecordDetailGate, SectionHead } from '../shared'

const PAGE_SIZE = 20
const STATUSES = ['DRAFT', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED']

export function PrescriptionsSection() {
  const { patient } = usePatientRecord()
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => prescriptionsApi.list(patient.id, { status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, status, offset])
  const columns: Column<Prescription>[] = [
    { key: 'prescribed', header: 'Prescribed', numeric: true, width: 180,
      render: (p) => <span className="cell-strong">{formatDateTime(p.prescribed_at)}</span> },
    { key: 'medicines', header: 'Medicines', render: (p) => (
      <span className="cell-stack"><span className="cell-strong">{p.items.map((i) => i.medicine_name).join(', ') || '—'}</span>
        <span className="cell-sub mono">{p.prescription_number}</span></span>) },
    { key: 'items', header: 'Items', numeric: true, priority: 'secondary', render: (p) => p.items.length },
    { key: 'prescriber', header: 'Prescriber', priority: 'secondary', render: (p) => p.prescriber_name },
    { key: 'status', header: 'Status', render: (p) => <StatusBadge status={p.status} size="sm" /> },
  ]
  return (
    <>
      <SectionHead title="Prescriptions" meta={<span>As prescribed · read-only</span>}>
        <Field label="Status">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
        </Field>
      </SectionHead>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Prescriptions" columns={columns} rows={result.data?.items} rowKey={(p) => p.id}
              loading={result.loading && !result.data} onRowClick={(p) => navigate(p.id)}
              rowLabel={(p) => `Open prescription ${p.prescription_number}`}
              empty={<EmptyState icon="prescriptions" title={status ? `No ${humanize(status).toLowerCase()} prescriptions` : 'No prescriptions recorded'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="prescriptions" /> : null}
          </>
        )}
      </Card>
    </>
  )
}

const STEPS = [
  { status: 'DRAFT', label: 'Prescribed', key: 'prescribed_at' },
  { status: 'ACTIVE', label: 'Active', key: 'activated_at' },
  { status: 'COMPLETED', label: 'Completed', key: 'completed_at' },
] as const

export function PrescriptionDetailPage() {
  const { patient } = usePatientRecord()
  const { prescriptionId = '' } = useParams()
  const result = useQuery((s) => prescriptionsApi.get(prescriptionId, s), [prescriptionId])
  const back = <LinkButton to={`/patients/${patient.id}/prescriptions`} variant="ghost" size="sm" icon="chevronLeft">All prescriptions</LinkButton>
  return (
    <RecordDetailGate result={result} patientId={patient.id} noun="Prescription" back={back}>
      {(p) => <PrescriptionDetail prescription={p} back={back} />}
    </RecordDetailGate>
  )
}

function PrescriptionDetail({ prescription: p, back }: { prescription: Prescription; back: ReactNode }) {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  // ON_HOLD sits between Active and Completed: show Active as the current step with the hold noted.
  const lifecycleStatus = p.status === 'ON_HOLD' ? 'ACTIVE' : p.status
  const steps = STEPS.map((step) => ({ status: step.status, label: step.label, at: p[step.key] }))
  return (
    <div className="stack">
      <div>{back}</div>
      {p.status === 'DRAFT' ? <Alert tone="warning" title="Draft prescription">This prescription has not been issued.</Alert> : null}
      {p.status === 'ON_HOLD' ? <Alert tone="warning" title="On hold">This prescription is currently on hold.</Alert> : null}
      <Card title={<span className="enc-head">Prescription <span className="mono">{p.prescription_number}</span> <StatusBadge status={p.status} size="sm" /></span>}
        actions={<ProvenanceTag kind="record" />}>
        <DescriptionList columns={3} items={[
          { label: 'Prescriber', value: p.prescriber_name },
          { label: 'Prescribed', value: formatDateTime(p.prescribed_at) },
          { label: 'Status', value: humanize(p.status) },
          { label: 'Activated', value: p.activated_at ? formatDateTime(p.activated_at) : null },
          { label: 'Completed', value: p.completed_at ? formatDateTime(p.completed_at) : null },
          { label: 'Encounter', value: canReadClinical('encounter.view')
            ? <Link to={`/patients/${patient.id}/encounters/${p.encounter_id}`}>View encounter</Link>
            : <span className="text-muted">Recorded in an encounter</span> },
          { label: 'Notes', value: p.notes, wide: true },
        ]} />
      </Card>
      <Card title="Lifecycle">
        <Lifecycle label="Prescription lifecycle" steps={steps} status={lifecycleStatus} cancelledAt={p.cancelled_at}
          cancellationReason={p.cancellation_reason} />
      </Card>
      <ItemsCard items={p.items} />
    </div>
  )
}

function ItemsCard({ items }: { items: PrescriptionItem[] }) {
  const sorted = [...items].sort((a, b) => a.line_number - b.line_number)
  return (
    <Card title="Items" padding="none" description="Exactly as prescribed">
      {sorted.length === 0 ? <EmptyState compact icon="prescriptions" title="No items on this prescription" /> : (
        <DataTable caption="Prescription items" rows={sorted} rowKey={(i) => i.id} density="compact"
          columns={[
            { key: 'line', header: '#', numeric: true, width: 40, render: (i) => i.line_number },
            { key: 'medicine', header: 'Medicine', render: (i) => (
              <span className="cell-stack"><span className="cell-strong">{i.medicine_name}</span>
                {i.code ? <span className="cell-sub mono">{codingLabel(i.code_system)} {i.code}</span> : null}
                {i.instructions ? <span className="cell-sub">{i.instructions}</span> : null}</span>) },
            { key: 'dose', header: 'Dose', numeric: true, render: (i) => <span className="value-strong">{prescriptionDose(i)}</span> },
            { key: 'route', header: 'Route', render: (i) => humanize(i.route) },
            { key: 'frequency', header: 'Frequency', render: (i) => (
              <span className="cell-stack"><span>{FREQUENCY_LABEL[i.frequency] ?? humanize(i.frequency)}</span>
                <span className="cell-sub mono">{i.frequency}</span></span>) },
            { key: 'duration', header: 'Duration', priority: 'secondary', render: (i) => prescriptionDuration(i) ?? <span className="text-subtle">—</span> },
            { key: 'quantity', header: 'Quantity', priority: 'secondary', render: (i) => prescriptionQuantity(i) ?? <span className="text-subtle">—</span> },
          ]} />
      )}
    </Card>
  )
}
