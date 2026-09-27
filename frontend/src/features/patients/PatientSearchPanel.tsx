/**
 * Patient search + filter + paginated results (GET /api/patients: q, status, limit, offset).
 * State lives in the URL (?q=&status=&offset=) so results are shareable and survive back/forward.
 */
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { patientsApi } from '../../api/endpoints'
import type { PatientDetail } from '../../api/types'
import type { Column } from '../../components/ui'
import { Avatar, Card, DataTable, EmptyState, ErrorState, Field, Input, Pagination, Select, StatusBadge } from '../../components/ui'
import { useDebounced } from '../../hooks/useDebounced'
import { useQuery } from '../../hooks/useQuery'
import { ageFromDob, formatDate, formatRelative, patientDisplayName, sexLabel } from '../../lib/format'

const PAGE_SIZE = 20

interface Props {
  onOpen: (patient: PatientDetail) => void
  title: string
  description?: string
  actions?: ReactNode
}

export function PatientSearchPanel({ onOpen, title, description, actions }: Props) {
  const [params, setParams] = useSearchParams()
  const [term, setTerm] = useState(params.get('q') ?? '')
  const debouncedTerm = useDebounced(term.trim(), 300)
  const status = params.get('status') ?? ''
  const offset = Number(params.get('offset') ?? 0) || 0

  // push the debounced search term into the URL (resetting to the first page)
  useEffect(() => {
    const current = params.get('q') ?? ''
    if (debouncedTerm === current) return
    const next = new URLSearchParams(params)
    if (debouncedTerm) next.set('q', debouncedTerm); else next.delete('q')
    next.delete('offset')
    setParams(next, { replace: true })
  }, [debouncedTerm, params, setParams])

  const q = params.get('q') ?? ''
  const result = useQuery((s) => patientsApi.list({ q: q || undefined, status: status || undefined, limit: PAGE_SIZE, offset }, s),
    [q, status, offset])

  function update(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    if (key !== 'offset') next.delete('offset')
    setParams(next)
  }

  const columns: Column<PatientDetail>[] = [
    { key: 'name', header: 'Patient', render: (p) => (
      <span className="plist__patient">
        <Avatar name={`${p.first_name} ${p.last_name}`} size={32} tone="neutral" />
        <span className="plist__who">
          <span className="plist__name">{patientDisplayName(p)}</span>
          <span className="plist__id mono">{p.patient_number}</span>
        </span>
      </span>) },
    { key: 'age', header: 'Age / sex', render: (p) => <span className="tabular">{ageFromDob(p.date_of_birth)} y · {sexLabel(p.sex)}</span> },
    { key: 'dob', header: 'Date of birth', priority: 'secondary', numeric: true,
      render: (p) => formatDate(`${p.date_of_birth}T00:00:00`) },
    { key: 'phone', header: 'Phone', priority: 'tertiary', render: (p) => (p.phone ? <span className="tabular">{p.phone}</span> : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'Status', render: (p) => <StatusBadge status={p.status} size="sm" /> },
    { key: 'registered', header: 'Registered', priority: 'secondary', render: (p) => <span className="text-muted">{formatRelative(p.created_at)}</span> },
  ]

  const filtered = Boolean(q || status)
  return (
    <Card padding="none" title={title} description={description} actions={actions}>
      <div className="plist__filters">
        <div className="plist__search">
          <Field label="Search">
            <Input icon="search" type="search" placeholder="Name, Patient ID, phone or email" value={term}
              onChange={(e) => setTerm(e.target.value)} autoComplete="off" spellCheck={false} />
          </Field>
        </div>
        <div className="plist__status">
          <Field label="Status">
            <Select value={status} onChange={(e) => update('status', e.target.value)}>
              <option value="">All patients</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </Select>
          </Field>
        </div>
      </div>
      {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
        <>
          <DataTable caption="Patients" columns={columns} rows={result.data?.items} rowKey={(p) => p.id}
            loading={result.loading && !result.data} onRowClick={onOpen}
            rowLabel={(p) => `Open record of ${patientDisplayName(p)}, ${p.patient_number}`}
            empty={filtered
              ? <EmptyState icon="search" title="No matching patients" description="Check the spelling, or search by Patient ID or phone number." />
              : <EmptyState icon="patients" title="No patients registered yet" />} />
          {result.data ? (
            <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} noun="patients"
              onChange={(value) => update('offset', value ? String(value) : '')} />
          ) : null}
        </>
      )}
    </Card>
  )
}
