/** Name lookups for workflow lists (patients and departments are referenced by id in workflow records). */
import { Link } from 'react-router-dom'
import { patientsApi, staffApi } from '../../api/endpoints'
import type { Department } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { useQuery } from '../../hooks/useQuery'
import { patientDisplayName } from '../../lib/format'

// Departments are reference data used on many rows: loaded once per page session. Patient identities are always
// read from the API (no client-side patient/clinical cache).
let departmentsCache: Promise<Department[]> | null = null

function loadDepartments(): Promise<Department[]> {
  if (!departmentsCache) {
    departmentsCache = staffApi.departments({ limit: 100 }).then((page) => page.items)
    departmentsCache.catch(() => { departmentsCache = null })
  }
  return departmentsCache
}

/** Patient name (and Patient ID) linking to the record; needs patient.view. */
export function PatientName({ id, to }: { id: string | null; to?: string }) {
  const { can } = useAuth()
  const enabled = Boolean(id) && can('patient.view')
  const patient = useQuery((signal) => patientsApi.get(id as string, signal), [id], { enabled })
  if (!id) return <span className="text-subtle">—</span>
  if (!enabled) return <span className="text-muted">Patient (restricted)</span>
  if (!patient.data) return <span className="text-subtle">{patient.error ? 'Patient' : 'Loading…'}</span>
  return (
    <span className="cell-stack">
      <Link to={to ?? `/patients/${id}`} onClick={(e) => e.stopPropagation()}>{patientDisplayName(patient.data)}</Link>
      <span className="cell-sub mono">{patient.data.patient_number}</span>
    </span>
  )
}

export function DepartmentName({ id }: { id: string | null }) {
  const { can } = useAuth()
  const departments = useQuery(() => loadDepartments(), [], { enabled: can('staff.view') })
  if (!id) return <span className="text-subtle">—</span>
  const match = departments.data?.find((d) => d.id === id)
  return <span>{match ? match.name : 'Department'}</span>
}
