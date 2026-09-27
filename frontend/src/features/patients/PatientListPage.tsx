import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { Alert, LinkButton, PageHeader } from '../../components/ui'
import { PatientSearchPanel } from './PatientSearchPanel'
import './patients.css'

export function PatientListPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  return (
    <>
      <PageHeader title="Patients" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Patients' }]}
        description="Find a patient by name, Patient ID, phone or email, then open their record."
        actions={can('patient.create') ? <LinkButton to="/patients/new" variant="primary" icon="plus">Register patient</LinkButton> : null} />
      {notice ? <div className="plist__notice"><Alert tone="success">{notice}</Alert></div> : null}
      <PatientSearchPanel title="Patient register" onOpen={(p) => navigate(`/patients/${p.id}`)} />
    </>
  )
}

/** Module entry points: clinical data is kept per patient, so each module starts by choosing the patient. */
function PatientFinderPage({ title, description, section }: { title: string; description: string; section: string }) {
  const navigate = useNavigate()
  return (
    <>
      <PageHeader title={title} breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: title }]} description={description} />
      <PatientSearchPanel title="Select a patient" onOpen={(p) => navigate(`/patients/${p.id}${section ? `/${section}` : ''}`)} />
    </>
  )
}

/** "Clinical records": opens the patient timeline (or the overview for users who cannot read the timeline). */
const FINDER_TARGETS = new Set(['timeline', 'vitals/new', 'notes/new', 'encounters/new'])

export function ClinicalRecordsPage() {
  const { canReadClinical } = useAuth()
  const [params] = useSearchParams()
  const next = params.get('next') ?? ''
  const section = FINDER_TARGETS.has(next) ? next : canReadClinical('timeline.view') ? 'timeline' : ''
  return <PatientFinderPage title="Clinical records" section={section}
    description="Clinical records are kept per patient. Select a patient to open their timeline, encounters, vitals, conditions, allergies and notes." />
}

/** UI-2 "Diagnostics": opens the patient's laboratory orders and reports. */
export function DiagnosticsModulePage() {
  return <PatientFinderPage title="Diagnostics" section="diagnostics"
    description="Laboratory orders, samples, results and clinical reports are kept per patient. Select a patient to view them (read-only)." />
}

/** UI-2 "Prescriptions": opens the patient's prescriptions. */
export function PrescriptionsModulePage() {
  return <PatientFinderPage title="Prescriptions" section="prescriptions"
    description="Prescriptions are kept per patient. Select a patient to view their prescriptions and items (read-only)." />
}
