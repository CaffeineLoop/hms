/**
 * UI-5 AI clinical analysis (Stages 7-10 backend; frontend integration only).
 *
 *   Observe → Analyze → Explain → Suggest for review → Stop
 *
 * - The four-day risk analysis is requested per patient (ai.analysis). Deterministic rules produce the signals; the
 *   model only explains them. Nothing here writes clinical records, orders or workflows.
 * - Stored analyses are AI suggestions awaiting human review (ai.review: acknowledge / dismiss). The review changes
 *   the AI record only.
 * - Everything shown comes from the API as returned; the UI adds no interpretation. Evidence ids are only labelled and
 *   linked to where the record lives in the patient chart.
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { aiApi } from '../../api/endpoints'
import type { RiskAnalysis, RiskSignal } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Icon } from '../../components/icons/Icon'
import type { Column } from '../../components/ui'
import {
  Alert, Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, ErrorState, Field, LinkButton, LoadingState, PageHeader,
  Pagination, ProvenancePanel, ProvenanceTag, Select, StatusBadge, Textarea,
} from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { useSubmit } from '../../hooks/useSubmit'
import { evidenceRef, reasonLabel } from '../../lib/ai'
import { formatDateTime, formatRelative, humanize } from '../../lib/format'
import { usePatientRecord } from '../patients/patientContext'
import { SectionHead, StaffName } from '../patients/shared'
import { PatientName } from '../workflows/lookups'
import { ProblemAlert } from '../writes/WriteControls'
import '../admin/admin.css'
import './ai.css'

const PAGE_SIZE = 20

// ---------------------------------------------------------------- shared

/** The AI boundary, always shown with AI content. */
export function AiPipeline() {
  const steps = ['Observe', 'Analyze', 'Explain', 'Suggest for review', 'Stop']
  return (
    <div className="ai-pipeline" role="note" aria-label="How the AI assistant works">
      <ol className="ai-pipeline__steps">
        {steps.map((s, i) => <li key={s} className={i === steps.length - 1 ? 'ai-pipeline__stop' : ''}>{s}</li>)}
      </ol>
      <p className="ai-pipeline__text">
        The assistant reads this patient's records (read-only), explains rule-based potential risk signals and suggests
        points for <strong>clinician review</strong>. It stops there: it never writes records, orders, prescriptions or
        diagnoses, and its suggestions are not confirmed clinical facts.
      </p>
    </div>
  )
}

function PriorityBadge({ priority }: { priority: string | null }) {
  if (!priority) return <span className="text-subtle">—</span>
  const tone = priority === 'HIGH' ? 'danger' : priority === 'MODERATE' ? 'warning' : 'neutral'
  return <Badge tone={tone} size="sm"><span title="Suggested priority for clinician review — not a severity score">Review priority · {humanize(priority)}</span></Badge>
}

function Horizon({ a }: { a: Pick<RiskAnalysis, 'reference_at' | 'horizon_end' | 'analysis_horizon_days'> }) {
  return (
    <span className="ai-horizon">
      <Icon name="calendar" size={14} />
      <span><strong>{a.analysis_horizon_days}-day horizon</strong>: {formatDateTime(a.reference_at)} → {formatDateTime(a.horizon_end)}</span>
    </span>
  )
}

function EvidenceLinks({ ids, patientId }: { ids: string[]; patientId: string }) {
  const { canReadClinical } = useAuth()
  if (!ids.length) return null
  return (
    <span className="ai-evidence">
      {ids.map((id) => {
        const ref = evidenceRef(id, patientId)
        const label = <>{ref.label} <span className="mono">{ref.shortId}</span></>
        return ref.link && (ref.link.permission === 'patient.view' || canReadClinical(ref.link.permission))
          ? <Link key={id} className="ai-evidence__ref" to={ref.link.to} title={id}>{label}</Link>
          : <span key={id} className="ai-evidence__ref" title={id}>{label}</span>
      })}
    </span>
  )
}

// ---------------------------------------------------------------- patient record: section

export function PatientAiSection() {
  const { patient } = usePatientRecord()
  const { can } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  const canRun = can('ai.analysis')
  const [offset, setOffset] = useState(0)
  const [confirm, setConfirm] = useState(false)
  const [refusal, setRefusal] = useState<{ title: string; message: string } | null>(null)
  const run = useSubmit()
  const caps = useQuery((s) => aiApi.capabilities(s), [], { enabled: canRun })
  const list = useQuery((s) => aiApi.list({ patient_id: patient.id, limit: PAGE_SIZE, offset }, s), [patient.id, offset])

  async function analyze() {
    setRefusal(null)
    const result = await run.run(() => aiApi.analyzeFourDayRisk(patient.id))
    setConfirm(false)
    if (!result) return
    const id = result.risk?.risk_analysis_id
    if (id) {
      navigate(id, { state: result.status === 'COMPLETED'
        ? { notice: 'Four-day risk analysis completed and stored for clinician review.', tone: 'success' }
        : { notice: `The assistant abstained: ${result.message}`, tone: 'warning' } })
    } else {
      setRefusal({ title: `Analysis ${humanize(result.status).toLowerCase()}${result.reason_code ? ` — ${reasonLabel(result.reason_code)}` : ''}`, message: result.message })
      list.reload()
    }
  }

  const columns: Column<RiskAnalysis>[] = [
    { key: 'created', header: 'Requested', numeric: true, width: 170, render: (a) => <span className="cell-strong">{formatDateTime(a.created_at)}</span> },
    { key: 'horizon', header: 'Four-day horizon', render: (a) => <span className="cell-sub">{formatDateTime(a.reference_at)} → {formatDateTime(a.horizon_end)}</span> },
    { key: 'result', header: 'Result', render: (a) => <span className="cell-stack"><StatusBadge status={a.status} size="sm" />
      {a.reason_code ? <span className="cell-sub">{reasonLabel(a.reason_code)}</span> : null}</span> },
    { key: 'signals', header: 'Signals', numeric: true, render: (a) => a.signals.length },
    { key: 'priority', header: 'Highest review priority', render: (a) => <PriorityBadge priority={a.max_priority} /> },
    { key: 'review', header: 'Review', render: (a) => <StatusBadge status={a.review_status} size="sm" /> },
  ]

  const disabled = caps.data && !caps.data.enabled
  return (
    <>
      {notice ? <div className="plist__notice"><Alert tone="success">{notice}</Alert></div> : null}
      <SectionHead title="AI analysis" meta={<><ProvenanceTag kind="ai" /><span>Suggestions for clinician review only</span></>}>
        {canRun ? <Button variant="primary" icon="ai" onClick={() => setConfirm(true)} disabled={Boolean(disabled)}>Run four-day risk analysis</Button> : null}
      </SectionHead>
      <AiPipeline />
      {disabled ? <Alert tone="warning" title="AI assistant not configured">The HMS AI assistant is currently disabled; analyses cannot be run.</Alert> : null}
      {caps.data && caps.data.enabled ? (
        <p className="text-muted ai-caps">AI layer: <span className="mono">{caps.data.provider}</span> · <span className="mono">{caps.data.model}</span>
          {' '}· read-only evidence tools available to you: {caps.data.tools.filter((t) => t.available_to_you).length} of {caps.data.tools.length}</p>
      ) : null}
      <ProblemAlert problem={run.problem} />
      {refusal ? <Alert tone="warning" title={refusal.title}>{refusal.message}</Alert> : null}
      {run.submitting ? <Card><LoadingState label="The assistant is analysing this patient's records (read-only)…" /></Card> : null}
      <Card padding="none" title="Stored four-day risk analyses" description="AI suggestions awaiting or after clinician review · newest first">
        {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : (
          <>
            <DataTable caption="AI risk analyses" columns={columns} rows={list.data?.items} rowKey={(a) => a.id}
              loading={list.loading && !list.data} onRowClick={(a) => navigate(a.id)} rowLabel={(a) => `Open AI analysis of ${formatDateTime(a.created_at)}`}
              empty={<EmptyState icon="ai" title="No AI analyses for this patient"
                description={canRun ? 'Run a four-day risk analysis to get potential risk signals for clinician review.' : undefined} />} />
            {list.data ? <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="analyses" /> : null}
          </>
        )}
      </Card>
      <ConfirmDialog open={confirm} title="Run four-day risk analysis" confirmLabel="Run analysis" tone="primary" busy={run.submitting}
        onCancel={() => setConfirm(false)} onConfirm={analyze}>
        <p>The assistant reads this patient's recent records (read-only), applies the rule-based signal checks for the next
          four days from now, and explains them. The result is stored as an <strong>AI suggestion for clinician review</strong>.
          It does not change the record or trigger any action.</p>
      </ConfirmDialog>
    </>
  )
}

// ---------------------------------------------------------------- analysis detail

export function RiskAnalysisDetailPage() {
  const { patient } = usePatientRecord()
  const { analysisId = '' } = useParams()
  const location = useLocation()
  const { notice, tone = 'success' } = (location.state as { notice?: string; tone?: 'success' | 'warning' } | null) ?? {}
  const result = useQuery((s) => aiApi.get(analysisId, s), [analysisId])
  const back = <LinkButton to={`/patients/${patient.id}/ai`} variant="ghost" size="sm" icon="chevronLeft">All AI analyses</LinkButton>
  const notFound = <Alert tone="danger" title="AI analysis not found for this patient">No AI analysis with this reference exists for this patient. {back}</Alert>

  if (result.error instanceof ApiError && result.error.status === 404) return notFound
  if (result.error) return <Card>{back}<ErrorState error={result.error} onRetry={result.error.isForbidden ? undefined : result.reload} /></Card>
  if (!result.data) return <LoadingState label="Loading AI analysis…" />
  // The by-id endpoint is not patient-scoped: never show another patient's analysis under this banner.
  if (result.data.patient_id !== patient.id) return notFound
  const a = result.data
  const explanations = new Map((a.output?.risk_signals ?? []).map((s) => [s.signal_id, s]))
  const cited = a.output?.evidence ?? []

  return (
    <div className="stack">
      {notice ? <Alert tone={tone}>{notice}</Alert> : null}
      <div>{back}</div>
      <AiPipeline />
      <Card title={<span className="enc-head">Four-day potential risk analysis <StatusBadge status={a.status} size="sm" />
        <StatusBadge status={a.review_status} size="sm" /></span>} actions={<ProvenanceTag kind="ai" />}
        description={<Horizon a={a} />}>
        <dl className="kv ai-meta">
          <dt>Requested</dt><dd>{formatDateTime(a.created_at)} by <StaffName staffId={a.requested_by_staff_id} /> ({humanize(a.trigger)}{a.trigger_event ? ` · ${a.trigger_event}` : ''})</dd>
          <dt>Highest review priority</dt><dd><PriorityBadge priority={a.max_priority} /></dd>
          <dt>Signal rules</dt><dd><span className="mono">{a.ruleset_id} v{a.ruleset_version}</span>{' '}
            {a.ruleset_validated ? <Badge tone="success" size="sm">Validated</Badge> : <Badge tone="warning" size="sm">Not clinically validated</Badge>}</dd>
          <dt>AI model</dt><dd><span className="mono">{a.provider} · {a.model}</span></dd>
        </dl>
        <p className="ai-disclaimer"><Icon name="info" size={14} /> {a.disclaimer}</p>
      </Card>

      {a.status !== 'COMPLETED' ? (
        <Alert tone="warning" title={`No analysis — ${reasonLabel(a.reason_code) ?? humanize(a.status)}`}>
          {a.output?.abstain_reason ?? 'The assistant did not produce an analysis for this request.'}
          {a.data_gaps.length ? <> Missing or insufficient data: {a.data_gaps.map((g) => g.replace(/\.$/, '')).join('; ')}.</> : null}
        </Alert>
      ) : null}

      {a.status === 'COMPLETED' || a.signals.length ? (
      <Card title="Potential risk signals" padding="none" actions={<ProvenanceTag kind="system">Rule-based signals</ProvenanceTag>}
        description="Produced by the HMS signal rules from the cited records. The AI explains them; it cannot add, remove or re-grade them.">
        {a.signals.length === 0 ? <EmptyState compact icon="checkCircle" title="No risk signals identified"
          description="No signal rule matched the available data. This is not a statement that the patient is at no risk." /> : (
          <ul className="ai-signals">
            {a.signals.map((s) => <SignalItem key={s.signal_id} signal={s} explanation={explanations.get(s.signal_id)?.explanation} patientId={a.patient_id} />)}
          </ul>
        )}
      </Card>
      ) : null}

      {a.output && a.output.status === 'ANALYSIS' ? (
        <ProvenancePanel kind="ai" title="AI explanation" meta={<Horizon a={a} />}>
          <p className="ai-text">{a.output.summary}</p>
          {a.output.observed_trends.length ? (
            <>
              <h4 className="ai-subhead">Observed trends</h4>
              <ul className="ai-list">{a.output.observed_trends.map((t, i) => <li key={i}>{t.description} <EvidenceLinks ids={t.evidence} patientId={a.patient_id} /></li>)}</ul>
            </>
          ) : null}
          {a.output.precautionary_suggestions.length ? (
            <>
              <h4 className="ai-subhead">Suggestions for clinician review</h4>
              <ul className="ai-list ai-list--suggest">{a.output.precautionary_suggestions.map((s, i) => <li key={i}><Badge tone="info" size="sm">For review</Badge> {s}</li>)}</ul>
            </>
          ) : null}
          <h4 className="ai-subhead">Limitations stated by the assistant</h4>
          <ul className="ai-list">{a.output.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </ProvenancePanel>
      ) : null}

      {a.data_gaps.length && a.status === 'COMPLETED' ? (
        <Card title="Data gaps" actions={<ProvenanceTag kind="system">Rule engine</ProvenanceTag>}>
          <ul className="ai-list">{a.data_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
        </Card>
      ) : null}

      {a.status === 'COMPLETED' || cited.length ? (
      <Card title="Evidence cited" padding="none" actions={<ProvenanceTag kind="record">Documented records</ProvenanceTag>}
        description="Records the analysis cites, as returned by the API. Links open where the record lives in the chart.">
        {cited.length === 0 ? <EmptyState compact icon="document" title="No evidence cited" /> : (
          <ul className="ai-cited">
            {cited.map((c) => (
              <li key={c.source_id}><EvidenceLinks ids={[c.source_id]} patientId={a.patient_id} /><span className="ai-cited__why">{c.relevance}</span></li>
            ))}
          </ul>
        )}
      </Card>
      ) : null}

      <ReviewPanel analysis={a} onReviewed={result.reload} />
    </div>
  )
}

function SignalItem({ signal: s, explanation, patientId }: { signal: RiskSignal; explanation?: string; patientId: string }) {
  return (
    <li className="ai-signal">
      <div className="ai-signal__head">
        <PriorityBadge priority={s.priority} />
        <span className="ai-signal__cat">{humanize(s.category)}</span>
        <span className="mono text-subtle">{s.signal_id} · {s.rule_id}</span>
      </div>
      <p className="ai-signal__title">{s.title}</p>
      <p className="ai-signal__detail">{s.detail}</p>
      <div className="ai-signal__evidence"><span className="text-muted">Based on:</span> <EvidenceLinks ids={s.evidence} patientId={patientId} /></div>
      {explanation ? (
        <div className="ai-signal__explain"><ProvenanceTag kind="ai">AI explanation</ProvenanceTag><p>{explanation}</p></div>
      ) : null}
    </li>
  )
}

function ReviewPanel({ analysis: a, onReviewed }: { analysis: RiskAnalysis; onReviewed: () => void }) {
  const { can } = useAuth()
  const [decision, setDecision] = useState('')
  const [comment, setComment] = useState('')
  const review = useSubmit()
  if (a.review_status !== 'PENDING_REVIEW') {
    return (
      <Card title="Clinician review" actions={<StatusBadge status={a.review_status} size="sm" />}>
        <p>{a.review_status === 'ACKNOWLEDGED' ? 'Acknowledged' : 'Dismissed'} by <StaffName staffId={a.reviewed_by_staff_id} />
          {a.reviewed_at ? <> on {formatDateTime(a.reviewed_at)} ({formatRelative(a.reviewed_at)})</> : null}.</p>
        {a.review_comment ? <p className="ai-text">“{a.review_comment}”</p> : null}
        <p className="text-muted">The review changes only this AI record. Any clinical action is taken separately by clinicians.</p>
      </Card>
    )
  }
  if (!can('ai.review')) {
    return <Card title="Clinician review"><p className="text-muted">Awaiting review by a clinician with the ai.review permission.</p></Card>
  }
  async function submit() {
    if (!decision) return review.reject({ decision: 'Choose acknowledge or dismiss.' }, 'Nothing was recorded.')
    const done = await review.run(() => aiApi.review(a.id, decision as 'ACKNOWLEDGED' | 'DISMISSED', comment.trim() || null))
    if (done) onReviewed()
  }
  return (
    <Card title="Clinician review" actions={<StatusBadge status="PENDING_REVIEW" size="sm" />}
      description="Record that you have reviewed these AI suggestions. This does not accept them as clinical facts or act on them.">
      <div className="stack" style={{ maxWidth: 560 }}>
        <ProblemAlert problem={review.problem} />
        <Field label="Decision" required error={review.errors.decision}>
          <Select value={decision} onChange={(e) => { setDecision(e.target.value); review.clearField('decision') }}>
            <option value="">Select…</option>
            <option value="ACKNOWLEDGED">Acknowledge — reviewed; any action is taken separately by clinicians</option>
            <option value="DISMISSED">Dismiss — not relevant or not supported</option>
          </Select>
        </Field>
        <Field label="Comment" hint="Optional" error={review.errors.comment}>
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} maxLength={1000} />
        </Field>
        <div><Button variant="primary" loading={review.submitting} onClick={submit}>Record review</Button></div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- /ai module: review queue

export function AiModulePage({ children }: { children?: ReactNode }) {
  const { canAny, can } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState('PENDING_REVIEW')
  const [offset, setOffset] = useState(0)
  const allowed = canAny('ai.analysis', 'ai.review')
  const list = useQuery((s) => aiApi.list({ review_status: status || undefined, limit: PAGE_SIZE, offset }, s), [status, offset], { enabled: allowed })
  const caps = useQuery((s) => aiApi.capabilities(s), [], { enabled: can('ai.analysis') })
  const header = <PageHeader title="AI analysis" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'AI analysis' }]}
    description="Four-day potential risk signals for clinician review. Run an analysis from a patient's record." />
  if (!allowed) {
    return <>{header}<Card><EmptyState icon="lock" title="Not available for your role" description="AI analysis requires ai.analysis or ai.review." /></Card></>
  }
  const columns: Column<RiskAnalysis>[] = [
    { key: 'created', header: 'Requested', numeric: true, width: 170, render: (a) => <span className="cell-strong">{formatDateTime(a.created_at)}</span> },
    { key: 'patient', header: 'Patient', render: (a) => <PatientName id={a.patient_id} to={`/patients/${a.patient_id}/ai/${a.id}`} /> },
    { key: 'result', header: 'Result', render: (a) => <StatusBadge status={a.status} size="sm" /> },
    { key: 'signals', header: 'Signals', numeric: true, render: (a) => a.signals.length },
    { key: 'priority', header: 'Highest review priority', render: (a) => <PriorityBadge priority={a.max_priority} /> },
    { key: 'review', header: 'Review', render: (a) => <StatusBadge status={a.review_status} size="sm" /> },
  ]
  return (
    <>
      {header}
      {children}
      <AiPipeline />
      {caps.data ? (
        <Card title="AI layer" actions={<ProvenanceTag kind="system" />}>
          <dl className="kv">
            <dt>Status</dt><dd>{caps.data.enabled ? <Badge tone="success" size="sm">Enabled</Badge> : <Badge tone="warning" size="sm">Not configured</Badge>}</dd>
            <dt>Provider · model</dt><dd className="mono">{caps.data.provider} · {caps.data.model}</dd>
            <dt>Analysis types</dt><dd>{caps.data.analysis_types.map(humanize).join(', ')}</dd>
            <dt>Read-only evidence tools</dt><dd>{caps.data.tools.map((t) => (
              <span key={t.name} className="ai-tool" title={t.description}>{t.name}{t.available_to_you ? '' : ' (not available to you)'}</span>))}</dd>
          </dl>
        </Card>
      ) : null}
      <div className="section-head">
        <div className="section-head__text"><h2 className="section-head__title">Review queue</h2>
          <div className="section-head__meta"><ProvenanceTag kind="ai" /><span>Stored four-day risk analyses</span></div></div>
        <div className="section-filters">
          <Field label="Review status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All</option>
              <option value="PENDING_REVIEW">Pending review</option>
              <option value="ACKNOWLEDGED">Acknowledged</option>
              <option value="DISMISSED">Dismissed</option>
            </Select>
          </Field>
        </div>
      </div>
      <Card padding="none">
        {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : (
          <>
            <DataTable caption="AI analyses" columns={columns} rows={list.data?.items} rowKey={(a) => a.id} loading={list.loading && !list.data}
              onRowClick={(a) => navigate(`/patients/${a.patient_id}/ai/${a.id}`)} rowLabel={(a) => `Open AI analysis of ${formatDateTime(a.created_at)}`}
              empty={<EmptyState icon="ai" title={status ? `No analyses ${humanize(status).toLowerCase()}` : 'No AI analyses'} />} />
            {list.data ? <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="analyses" /> : null}
          </>
        )}
      </Card>
    </>
  )
}
