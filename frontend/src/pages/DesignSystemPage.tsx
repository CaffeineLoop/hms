/**
 * Design-system reference (development builds only). Renders every reusable component so later UI stages
 * — and reviewers — can verify the visual language in one place. All sample content here is EXAMPLE DATA.
 */
import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  Alert, Avatar, Badge, Button, Card, ConfirmDialog, DataTable, Drawer, EmptyState, ErrorState, Field, IconButton,
  Input, LoadingState, Modal, PageHeader, ProvenancePanel, ProvenanceTag, Select, StatCard, StatusBadge, Tabs, Textarea,
} from '../components/ui'
import type { Column } from '../components/ui'
import './DesignSystemPage.css'

const COLORS: Array<[string, string[]]> = [
  ['Neutral', ['--gray-25', '--gray-50', '--gray-100', '--gray-150', '--gray-200', '--gray-300', '--gray-400', '--gray-500', '--gray-600', '--gray-700', '--gray-800', '--gray-900']],
  ['Primary', ['--primary-50', '--primary-100', '--primary-200', '--primary-400', '--primary-500', '--primary-600', '--primary-700', '--primary-800']],
  ['Status', ['--success-solid', '--warning-solid', '--danger-solid', '--info-solid', '--neutral-solid']],
  ['Provenance', ['--record-rule', '--system-border', '--system-fg', '--ai-accent', '--ai-border', '--ai-bg']],
]
const TYPE: Array<[string, string, number]> = [
  ['Page title', '--text-3xl', 600], ['Section title', '--text-xl', 600], ['Card title', '--text-lg', 600],
  ['Body', '--text-base', 400], ['Small / meta', '--text-sm', 400], ['Caption', '--text-xs', 500],
]

interface ExampleRow { id: string; name: string; number: string; ward: string; status: string; value: string }
const EXAMPLE_ROWS: ExampleRow[] = [
  { id: '1', name: 'EXAMPLE, Patient One', number: 'PAT-000001', ward: 'Medical ward A', status: 'ADMITTED', value: '38.9 °C' },
  { id: '2', name: 'EXAMPLE, Patient Two', number: 'PAT-000002', ward: 'Outpatients', status: 'IN_PROGRESS', value: '36.8 °C' },
  { id: '3', name: 'EXAMPLE, Patient Three', number: 'PAT-000003', ward: 'Surgical ward B', status: 'DISCHARGED', value: '37.1 °C' },
]

export function DesignSystemPage() {
  const [tab, setTab] = useState('components')
  const [modal, setModal] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [lastAction, setLastAction] = useState<string | null>(null)

  const columns: Column<ExampleRow>[] = [
    { key: 'name', header: 'Patient', render: (r) => <strong>{r.name}</strong> },
    { key: 'number', header: 'Patient ID', render: (r) => <span className="mono">{r.number}</span> },
    { key: 'ward', header: 'Location', priority: 'secondary', render: (r) => r.ward },
    { key: 'value', header: 'Temperature', align: 'right', numeric: true, priority: 'tertiary', render: (r) => r.value },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} size="sm" /> },
  ]

  return (
    <>
      <PageHeader title="Design system" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Design system' }]}
        description="Reference for the HMS visual language. Development builds only; all sample content is example data."
        meta={<Badge tone="warning">Example data only</Badge>} />

      <Tabs label="Design system sections" value={tab} onChange={setTab}
        items={[{ id: 'components', label: 'Components' }, { id: 'foundations', label: 'Foundations' }, { id: 'clinical', label: 'Clinical patterns' }]}>
        {tab === 'foundations' ? (
          <div className="stack ds">
            <Card title="Colour tokens">
              <div className="stack">
                {COLORS.map(([group, tokens]) => (
                  <div key={group}>
                    <p className="ds__label">{group}</p>
                    <div className="ds__swatches">
                      {tokens.map((t) => (
                        <div key={t} className="ds__swatch"><span style={{ background: `var(${t})` }} /><code>{t}</code></div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Typography">
              <div className="stack">
                {TYPE.map(([label, token, weight]) => (
                  <div key={label} className="ds__type">
                    <code>{token}</code>
                    <span style={{ fontSize: `var(${token})`, fontWeight: weight }}>{label} — The quick brown fox 0123456789</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        ) : tab === 'clinical' ? (
          <div className="stack ds">
            <Alert tone="info" title="Provenance is always visible">
              Documented records, system status and AI suggestions are styled differently so AI output can never be
              mistaken for a confirmed diagnosis or a record.
            </Alert>
            <ProvenancePanel kind="record" title="Condition: Malaria (suspected)" meta="Example · recorded by Dr Example">
              Documented by a clinician in the patient record.
            </ProvenancePanel>
            <ProvenancePanel kind="system" title="Laboratory order: Released" meta="Example · workflow status">
              The order moved through collection, processing and verification.
            </ProvenancePanel>
            <ProvenancePanel kind="ai" title="Potential concern: rising temperature trend" meta="Example · four-day horizon"
              footer={<><Button size="sm" variant="secondary">Acknowledge</Button><Button size="sm" variant="ghost">Dismiss</Button></>}>
              Temperature readings may warrant clinical review. This is example text illustrating the AI suggestion style.
            </ProvenancePanel>
            <div className="cluster"><ProvenanceTag kind="record" /><ProvenanceTag kind="system" /><ProvenanceTag kind="ai" /></div>
          </div>
        ) : (
          <div className="stack ds">
            <Card title="Buttons">
              <div className="stack">
                <div className="cluster">
                  <Button variant="primary">Primary</Button><Button>Secondary</Button><Button variant="ghost">Ghost</Button>
                  <Button variant="danger">Danger</Button><Button variant="danger-ghost">Danger ghost</Button>
                  <Button variant="primary" loading>Saving</Button><Button disabled>Disabled</Button>
                </div>
                <div className="cluster">
                  <Button size="sm" icon="plus">Small</Button><Button icon="plus">Medium</Button><Button size="lg" icon="plus">Large</Button>
                  <IconButton icon="more" label="More actions" variant="secondary" /><IconButton icon="bell" label="Notifications" badge={3} />
                </div>
              </div>
            </Card>

            <Card title="Form controls">
              <div className="ds__form">
                <Field label="Patient ID" hint="Format PAT-000000"><Input placeholder="PAT-000123" /></Field>
                <Field label="Search" ><Input icon="search" placeholder="Name, Patient ID or phone" /></Field>
                <Field label="Encounter type" required>
                  <Select defaultValue=""><option value="" disabled>Select…</option><option>Outpatient</option><option>Emergency</option><option>Inpatient</option></Select>
                </Field>
                <Field label="Temperature" error="Enter a value between 25 and 45 °C"><Input defaultValue="52" suffix="°C" /></Field>
                <div className="ds__span2"><Field label="Clinical note" hint="Free text; stored exactly as written"><Textarea placeholder="Example note…" /></Field></div>
              </div>
            </Card>

            <Card title="Badges & status">
              <div className="stack">
                <div className="cluster">
                  <Badge>Neutral</Badge><Badge tone="primary">Primary</Badge><Badge tone="success">Success</Badge>
                  <Badge tone="warning">Warning</Badge><Badge tone="danger">Danger</Badge><Badge tone="info">Info</Badge>
                  <Badge variant="outline">Outline</Badge><Badge tone="danger" variant="solid">Solid</Badge>
                </div>
                <div className="cluster">
                  {['OPEN', 'IN_PROGRESS', 'COMPLETED', 'URGENT', 'HIGH', 'SUSPECTED', 'RELEASED', 'PENDING_REVIEW', 'DENIED'].map((s) => <StatusBadge key={s} status={s} />)}
                </div>
              </div>
            </Card>

            <Card title="Alerts">
              <div className="stack">
                <Alert tone="info" title="Information">Neutral guidance for the user.</Alert>
                <Alert tone="success" title="Saved">The record was saved and attributed to you.</Alert>
                <Alert tone="warning" title="Check before continuing">This patient has a documented allergy.</Alert>
                <Alert tone="danger" title="Action failed" onDismiss={() => undefined}>The service could not be reached.</Alert>
              </div>
            </Card>

            <Card title="Table" description="Responsive: secondary/tertiary columns hide on smaller screens; first column stays pinned" padding="none">
              <DataTable caption="Example patients" columns={columns} rows={EXAMPLE_ROWS} rowKey={(r) => r.id}
                onRowClick={(r) => setLastAction(`Opened ${r.number}`)} rowLabel={(r) => `Open ${r.name}`} />
            </Card>
            {lastAction ? <Alert tone="neutral" onDismiss={() => setLastAction(null)}>{lastAction}</Alert> : null}

            <Card title="Overlays">
              <div className="cluster">
                <Button onClick={() => setModal(true)}>Open modal</Button>
                <Button onClick={() => setDrawer(true)}>Open drawer</Button>
                <Button variant="danger-ghost" icon="trash" onClick={() => setConfirm(true)}>Destructive action</Button>
              </div>
            </Card>

            <div className="ds__stats">
              <StatCard label="Example metric" value={128} icon="patients" hint="Example data" />
              <StatCard label="Loading metric" value={undefined} icon="workflows" loading />
              <StatCard label="Restricted metric" value={undefined} icon="bed" unavailable="Not available for your role" />
              <StatCard label="AI metric" value={4} icon="ai" tone="ai" hint="Pending clinician review" />
            </div>

            <div className="grid-12">
              <Card className="span-4" title="Empty state"><EmptyState compact title="No results" description="Try a different search." /></Card>
              <Card className="span-4" title="Loading state"><LoadingState label="Loading records…" /></Card>
              <Card className="span-4" title="Error state"><ErrorState compact error={new ApiError(503, 'The HMS service is temporarily unavailable.', null)} onRetry={() => undefined} /></Card>
            </div>
            <div className="cluster"><Avatar name="Example Clinician" /><Avatar name="Second Example" tone="neutral" /></div>
          </div>
        )}
      </Tabs>

      <Modal open={modal} onClose={() => setModal(false)} title="Example modal" description="Focus is trapped; Escape closes."
        footer={<><Button onClick={() => setModal(false)}>Cancel</Button><Button variant="primary" onClick={() => setModal(false)}>Continue</Button></>}>
        <Field label="Reason"><Input data-autofocus placeholder="Example input" /></Field>
      </Modal>
      <Drawer open={drawer} onClose={() => setDrawer(false)} title="Example drawer" description="Side panel for details and quick edits.">
        <p className="text-muted">Drawer content (example).</p>
      </Drawer>
      <ConfirmDialog open={confirm} onCancel={() => setConfirm(false)}
        onConfirm={() => { setConfirm(false); setLastAction('Confirmed the example destructive action') }}
        title="Cancel this example order?" confirmLabel="Cancel order" confirmationText="PAT-000001">
        This cannot be undone. The action will be recorded in the audit trail with your name.
      </ConfirmDialog>
    </>
  )
}
