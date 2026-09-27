/**
 * UI-2 Diagnostics (read-only): laboratory orders with their samples and results, and clinical reports.
 * GET /patients/{id}/lab-orders, /api/lab-orders/{id}, /patients/{id}/reports, /api/reports/{id}.
 * Values, reference ranges and laboratory flags are shown exactly as recorded; the UI derives no interpretation.
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { diagnosticsApi } from '../../../api/endpoints'
import type { LabOrder, LabResult, LabSample, Report } from '../../../api/types'
import { useAuth } from '../../../auth/useAuth'
import type { Column } from '../../../components/ui'
import {
  Alert, Badge, Card, DataTable, DescriptionList, EmptyState, ErrorState, Field, LinkButton, Pagination, ProvenanceTag,
  Select, StatusBadge,
} from '../../../components/ui'
import { useQuery } from '../../../hooks/useQuery'
import {
  codingLabel, INTERPRETATION_LABEL, INTERPRETATION_TONE, LAB_ORDER_STEPS, labReferenceRange, labResultValue,
} from '../../../lib/clinical'
import { formatDateTime, humanize } from '../../../lib/format'
import { usePatientRecord } from '../patientContext'
import { Lifecycle, RecordDetailGate, SectionHead } from '../shared'

const PAGE_SIZE = 20
const LAB_STATUSES = ['ORDERED', 'SAMPLE_COLLECTED', 'PROCESSING', 'RESULT_ENTERED', 'VERIFIED', 'RELEASED', 'CANCELLED']
const REPORT_STATUSES = ['DRAFT', 'VERIFIED', 'RELEASED', 'CANCELLED']
const REPORT_TYPES = ['LABORATORY', 'IMAGING', 'CONSULTATION', 'DISCHARGE', 'PROCEDURE', 'OTHER']

function Muted() {
  return <span className="text-subtle">—</span>
}

function Coding({ system, code }: { system: string | null; code: string | null }) {
  return code ? <span className="cell-sub mono">{codingLabel(system)} {code}</span> : null
}

// ---------------------------------------------------------------- section (lists)

export function DiagnosticsSection() {
  const { canReadClinical } = useAuth()
  const [params, setParams] = useSearchParams()
  const canLab = canReadClinical('lab.view')
  const canReports = canReadClinical('report.view')
  const view = params.get('view') === 'reports' && canReports ? 'reports' : canLab ? 'lab' : 'reports'
  return (
    <>
      <SectionHead title="Diagnostics" meta={<span>Laboratory and clinical reports, as recorded · read-only</span>} />
      {canLab && canReports ? (
        <div className="tl-toolbar">
          <div className="chips" role="group" aria-label="Diagnostics view">
            <button type="button" className="chip" aria-pressed={view === 'lab'} onClick={() => setParams({}, { replace: true })}>
              Laboratory orders</button>
            <button type="button" className="chip" aria-pressed={view === 'reports'} onClick={() => setParams({ view: 'reports' }, { replace: true })}>
              Reports</button>
          </div>
        </div>
      ) : null}
      {view === 'lab' ? <LabOrdersList /> : <ReportsList />}
    </>
  )
}

function LabOrdersList() {
  const { patient } = usePatientRecord()
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => diagnosticsApi.labOrders(patient.id, { status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [patient.id, status, offset])
  const columns: Column<LabOrder>[] = [
    { key: 'ordered', header: 'Ordered', numeric: true, width: 180, render: (o) => <span className="cell-strong">{formatDateTime(o.ordered_at)}</span> },
    { key: 'test', header: 'Test', render: (o) => (
      <span className="cell-stack"><span className="cell-strong">{o.test_name}</span>
        <span className="cell-sub mono">{o.order_number}</span></span>) },
    { key: 'priority', header: 'Priority', render: (o) => <StatusBadge status={o.priority} size="sm" /> },
    { key: 'status', header: 'Status', render: (o) => <StatusBadge status={o.status} size="sm" /> },
    { key: 'results', header: 'Results', numeric: true, priority: 'secondary',
      render: (o) => (o.results.length ? `${o.results.length} recorded` : <Muted />) },
    { key: 'by', header: 'Ordered by', priority: 'tertiary', render: (o) => o.ordered_by },
  ]
  return (
    <Card padding="none" title="Laboratory orders" description="Newest first"
      actions={<Field label="Status">
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
          <option value="">All statuses</option>
          {LAB_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </Select>
      </Field>}>
      {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
        <>
          <DataTable caption="Laboratory orders" columns={columns} rows={result.data?.items} rowKey={(o) => o.id}
            loading={result.loading && !result.data} onRowClick={(o) => navigate(`lab-orders/${o.id}`)}
            rowLabel={(o) => `Open lab order ${o.order_number}: ${o.test_name}`}
            empty={<EmptyState icon="diagnostics" title={status ? `No ${humanize(status).toLowerCase()} lab orders` : 'No laboratory orders recorded'} />} />
          {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="lab orders" /> : null}
        </>
      )}
    </Card>
  )
}

function ReportsList() {
  const { patient } = usePatientRecord()
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery((s) => diagnosticsApi.reports(patient.id,
    { status: status || undefined, report_type: type || undefined, limit: PAGE_SIZE, offset }, s), [patient.id, status, type, offset])
  const columns: Column<Report>[] = [
    { key: 'effective', header: 'Date', numeric: true, width: 180, render: (r) => <span className="cell-strong">{formatDateTime(r.effective_at)}</span> },
    { key: 'title', header: 'Report', render: (r) => (
      <span className="cell-stack"><span className="cell-strong">{r.title}</span><span className="cell-sub">{humanize(r.report_type)}</span></span>) },
    { key: 'author', header: 'Author', priority: 'secondary', render: (r) => r.author_name },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} size="sm" /> },
  ]
  return (
    <Card padding="none" title="Reports" description="Newest first"
      actions={<span className="cluster">
        <Field label="Type">
          <Select value={type} onChange={(e) => { setType(e.target.value); setOffset(0) }}>
            <option value="">All types</option>
            {REPORT_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
        </Field>
        <Field label="Status">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
            <option value="">All statuses</option>
            {REPORT_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
        </Field>
      </span>}>
      {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
        <>
          <DataTable caption="Reports" columns={columns} rows={result.data?.items} rowKey={(r) => r.id}
            loading={result.loading && !result.data} onRowClick={(r) => navigate(`reports/${r.id}`)}
            rowLabel={(r) => `Open report: ${r.title}`}
            empty={<EmptyState icon="document" title={status || type ? 'No reports match these filters' : 'No reports recorded'} />} />
          {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="reports" /> : null}
        </>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- lab order detail

function BackToDiagnostics({ view }: { view?: 'reports' }) {
  const { patient } = usePatientRecord()
  return <LinkButton to={`/patients/${patient.id}/diagnostics${view ? '?view=reports' : ''}`} variant="ghost" size="sm" icon="chevronLeft">
    All diagnostics</LinkButton>
}

function EncounterLink({ encounterId }: { encounterId: string | null }) {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  if (!encounterId) return null
  return canReadClinical('encounter.view')
    ? <Link to={`/patients/${patient.id}/encounters/${encounterId}`}>View encounter</Link>
    : <span className="text-muted">Recorded in an encounter</span>
}

export function LabOrderDetailPage() {
  const { patient } = usePatientRecord()
  const { orderId = '' } = useParams()
  const result = useQuery((s) => diagnosticsApi.labOrder(orderId, s), [orderId])
  const back = <BackToDiagnostics />
  return (
    <RecordDetailGate result={result} patientId={patient.id} noun="Lab order" back={back}>
      {(o) => <LabOrderDetail order={o} back={back} />}
    </RecordDetailGate>
  )
}

function LabOrderDetail({ order: o, back }: { order: LabOrder; back: ReactNode }) {
  const firstSample = o.samples.length ? [...o.samples].sort((a, b) => a.collected_at.localeCompare(b.collected_at))[0] : null
  const steps = LAB_ORDER_STEPS.map((step) => ({
    status: step.status, label: step.label,
    at: step.status === 'SAMPLE_COLLECTED' ? firstSample?.collected_at ?? null : step.at ? o[step.at] : null,
  }))
  const unreleased = o.results.length > 0 && o.status !== 'RELEASED' && o.status !== 'CANCELLED'
  return (
    <div className="stack">
      <div>{back}</div>
      <Card title={<span className="enc-head">{o.test_name} <StatusBadge status={o.status} size="sm" /></span>}
        description={<span className="mono">{o.order_number}</span>} actions={<ProvenanceTag kind="record" />}>
        <DescriptionList columns={3} items={[
          { label: 'Test', value: <span className="cell-stack"><span>{o.test_name}</span><Coding system={o.code_system} code={o.system_code} /></span> },
          { label: 'Priority', value: <StatusBadge status={o.priority} size="sm" /> },
          { label: 'Status', value: humanize(o.status) },
          { label: 'Ordered', value: formatDateTime(o.ordered_at) },
          { label: 'Ordered by', value: o.ordered_by },
          { label: 'Encounter', value: <EncounterLink encounterId={o.encounter_id} /> },
          { label: 'Verified by', value: o.verified_by },
          { label: 'Verified', value: o.verified_at ? formatDateTime(o.verified_at) : null },
          { label: 'Released', value: o.released_at ? formatDateTime(o.released_at) : null },
          { label: 'Clinical indication', value: o.clinical_indication, wide: true },
        ]} />
      </Card>
      <Card title="Lifecycle" description="As recorded by the laboratory workflow">
        <Lifecycle label="Lab order lifecycle" steps={steps} status={o.status} cancelledAt={o.cancelled_at}
          cancellationReason={o.cancellation_reason} />
      </Card>
      <SamplesCard samples={o.samples} />
      {unreleased ? (
        <Alert tone="warning" title="Results not yet released">
          {o.status === 'VERIFIED' ? 'These results are verified but have not been released by the laboratory.'
            : 'These results have not been verified or released by the laboratory. They are shown as entered and may change.'}
        </Alert>
      ) : null}
      <ResultsCard results={o.results} />
    </div>
  )
}

function SamplesCard({ samples }: { samples: LabSample[] }) {
  return (
    <Card title="Samples" padding="none">
      <DataTable caption="Samples" rows={samples} rowKey={(s) => s.id} density="compact"
        empty={<EmptyState compact icon="diagnostics" title="No sample collected yet" />}
        columns={[
          { key: 'accession', header: 'Accession', render: (s) => <span className="mono">{s.accession_number}</span> },
          { key: 'specimen', header: 'Specimen', render: (s) => humanize(s.specimen_type) },
          { key: 'collected', header: 'Collected', numeric: true, render: (s) => formatDateTime(s.collected_at) },
          { key: 'by', header: 'Collected by', render: (s) => s.collected_by },
          { key: 'notes', header: 'Notes', priority: 'secondary', render: (s) => s.notes ?? <Muted /> },
        ]} />
    </Card>
  )
}

function ResultsCard({ results }: { results: LabResult[] }) {
  return (
    <Card title="Results" padding="none" description="Values, reference ranges and flags exactly as recorded by the laboratory">
      <DataTable caption="Results" rows={results} rowKey={(r) => r.id} density="compact"
        empty={<EmptyState compact icon="diagnostics" title="No results entered yet" />}
        columns={[
          { key: 'analyte', header: 'Analyte', render: (r) => (
            <span className="cell-stack"><span className="cell-strong">{r.analyte_name}</span><Coding system={r.code_system} code={r.system_code} />
              {r.notes ? <span className="cell-sub">{r.notes}</span> : null}</span>) },
          { key: 'value', header: 'Value', align: 'right', numeric: true, render: (r) => <span className="value-strong">{labResultValue(r)}</span> },
          { key: 'range', header: 'Reference range', numeric: true, render: (r) => labReferenceRange(r) ?? <Muted /> },
          { key: 'flag', header: 'Lab flag', render: (r) => (r.interpretation
            ? <Badge tone={INTERPRETATION_TONE[r.interpretation]} size="sm">{INTERPRETATION_LABEL[r.interpretation]}</Badge> : <Muted />) },
          { key: 'resulted', header: 'Resulted', numeric: true, priority: 'secondary', render: (r) => formatDateTime(r.resulted_at) },
          { key: 'by', header: 'Entered by', priority: 'tertiary', render: (r) => r.entered_by },
        ]} />
    </Card>
  )
}

// ---------------------------------------------------------------- report detail

const REPORT_STEPS = [
  { status: 'DRAFT', label: 'Draft', key: 'created_at' },
  { status: 'VERIFIED', label: 'Verified', key: 'verified_at' },
  { status: 'RELEASED', label: 'Released', key: 'released_at' },
] as const

export function ReportDetailPage() {
  const { patient } = usePatientRecord()
  const { reportId = '' } = useParams()
  const result = useQuery((s) => diagnosticsApi.report(reportId, s), [reportId])
  const back = <BackToDiagnostics view="reports" />
  return (
    <RecordDetailGate result={result} patientId={patient.id} noun="Report" back={back}>
      {(r) => <ReportDetail report={r} back={back} />}
    </RecordDetailGate>
  )
}

function ReportDetail({ report: r, back }: { report: Report; back: ReactNode }) {
  const { patient } = usePatientRecord()
  const { canReadClinical } = useAuth()
  const steps = REPORT_STEPS.map((step) => ({ status: step.status, label: step.label, at: r[step.key] }))
  return (
    <div className="stack">
      <div>{back}</div>
      {r.status === 'DRAFT' || r.status === 'VERIFIED' ? (
        <Alert tone="warning" title={r.status === 'DRAFT' ? 'Draft report' : 'Verified, not yet released'}>
          This report has not been released. Its content is shown as currently recorded and may change.
        </Alert>
      ) : null}
      <Card title={<span className="enc-head">{r.title} <StatusBadge status={r.status} size="sm" /></span>}
        description={humanize(r.report_type)} actions={<ProvenanceTag kind="record" />}>
        <DescriptionList columns={3} items={[
          { label: 'Type', value: humanize(r.report_type) },
          { label: 'Date', value: formatDateTime(r.effective_at) },
          { label: 'Author', value: r.author_name },
          { label: 'Requested by', value: r.requested_by },
          { label: 'Requested', value: r.requested_at ? formatDateTime(r.requested_at) : null },
          { label: 'Coding', value: r.code ? <span className="mono">{codingLabel(r.code_system)} {r.code}</span> : null },
          { label: 'Verified by', value: r.verified_by },
          { label: 'Verified', value: r.verified_at ? formatDateTime(r.verified_at) : null },
          { label: 'Released', value: r.released_at ? formatDateTime(r.released_at) : null },
          { label: 'Encounter', value: <EncounterLink encounterId={r.encounter_id} /> },
          ...(r.lab_order_id ? [{ label: 'Lab order', value: canReadClinical('lab.view')
            ? <Link to={`/patients/${patient.id}/diagnostics/lab-orders/${r.lab_order_id}`}>Open lab order</Link>
            : <span className="text-muted">Linked lab order</span> }] : []),
        ]} />
      </Card>
      <Card title="Lifecycle">
        <Lifecycle label="Report lifecycle" steps={steps} status={r.status} cancelledAt={r.cancelled_at} cancellationReason={r.cancellation_reason} />
      </Card>
      <Card title="Report">
        {r.content ? <div className="report-body">{r.content}</div> : <EmptyState compact icon="document" title="No report text recorded" />}
      </Card>
      <Card title="Conclusion">
        {r.conclusion ? <div className="report-body">{r.conclusion}</div> : <span className="dlist__empty">Not recorded</span>}
      </Card>
    </div>
  )
}
