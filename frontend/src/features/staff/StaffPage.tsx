/**
 * Staff directory (UI-6 integration): read-only list of staff members and their departments
 * (GET /api/staff, /api/departments; staff.view). Staff administration is not part of the UI.
 */
import { useState } from 'react'
import { staffApi } from '../../api/endpoints'
import type { StaffMember } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import type { Column } from '../../components/ui'
import { Card, DataTable, EmptyState, ErrorState, Field, Input, PageHeader, Pagination, ProvenanceTag, Select, StatusBadge } from '../../components/ui'
import { useDebounced } from '../../hooks/useDebounced'
import { useQuery } from '../../hooks/useQuery'
import { humanize } from '../../lib/format'
import '../patients/patients.css'

const PAGE_SIZE = 25
const DESIGNATIONS = ['DOCTOR', 'CLINICAL_OFFICER', 'NURSE', 'MIDWIFE', 'LAB_TECHNICIAN', 'PHARMACIST', 'RADIOGRAPHER', 'RECEPTIONIST', 'ADMINISTRATOR', 'OTHER']

export function StaffPage() {
  const { can } = useAuth()
  const [q, setQ] = useState('')
  const [department, setDepartment] = useState('')
  const [designation, setDesignation] = useState('')
  const [status, setStatus] = useState('ACTIVE')
  const [offset, setOffset] = useState(0)
  const search = useDebounced(q, 300)
  const allowed = can('staff.view')
  const departments = useQuery((s) => staffApi.departments({ limit: 100 }, s), [], { enabled: allowed })
  const result = useQuery((s) => staffApi.list({ q: search || undefined, department_id: department || undefined,
    status: status || undefined, limit: PAGE_SIZE, offset, ...(designation ? { designation } : {}) }, s),
  [search, department, designation, status, offset], { enabled: allowed })
  const deptName = (id: string) => departments.data?.items.find((d) => d.id === id)?.name ?? 'Department'
  const header = <PageHeader title="Staff" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Staff' }]}
    description="Staff directory and departments (read-only)." />
  if (!allowed) return <>{header}<Card><EmptyState icon="lock" title="Not available for your role" description="The staff directory requires staff.view." /></Card></>

  const columns: Column<StaffMember & { phone?: string | null; email?: string | null }>[] = [
    { key: 'name', header: 'Name', render: (m) => <span className="cell-stack"><span className="cell-strong">{m.full_name}</span>
      <span className="cell-sub mono">{m.employee_code}</span></span> },
    { key: 'designation', header: 'Designation', render: (m) => humanize(m.designation) },
    { key: 'department', header: 'Department', render: (m) => deptName(m.department_id) },
    { key: 'contact', header: 'Contact', priority: 'secondary', render: (m) => (m.phone || m.email
      ? <span className="cell-stack">{m.phone ? <span>{m.phone}</span> : null}{m.email ? <span className="cell-sub">{m.email}</span> : null}</span>
      : <span className="text-subtle">—</span>) },
    { key: 'status', header: 'Status', render: (m) => <StatusBadge status={m.status} size="sm" /> },
  ]
  return (
    <>
      {header}
      <div className="section-head">
        <div className="section-head__text"><h2 className="section-head__title">Directory</h2>
          <div className="section-head__meta"><ProvenanceTag kind="system">Staff records</ProvenanceTag></div></div>
        <div className="section-filters">
          <Field label="Search"><Input type="search" icon="search" value={q} placeholder="Name or code" onChange={(e) => { setQ(e.target.value); setOffset(0) }} /></Field>
          <Field label="Department">
            <Select value={department} onChange={(e) => { setDepartment(e.target.value); setOffset(0) }}>
              <option value="">All departments</option>
              {departments.data?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          <Field label="Designation">
            <Select value={designation} onChange={(e) => { setDesignation(e.target.value); setOffset(0) }}>
              <option value="">All designations</option>
              {DESIGNATIONS.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
            </Select>
          </Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}>
              <option value="">All</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </Select>
          </Field>
        </div>
      </div>
      <Card padding="none">
        {result.error ? <ErrorState error={result.error} onRetry={result.reload} /> : (
          <>
            <DataTable caption="Staff" columns={columns} rows={result.data?.items} rowKey={(m) => m.id} loading={result.loading && !result.data}
              empty={<EmptyState icon="staff" title={q || department || designation ? 'No staff match these filters' : 'No staff members'} />} />
            {result.data ? <Pagination total={result.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} noun="staff members" /> : null}
          </>
        )}
      </Card>
    </>
  )
}
