/** /patients/:patientId/* — loads the patient once; banner + permitted section tabs + the active section. */
import { useCallback, useMemo, useState } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import { patientsApi } from '../../api/endpoints'
import { useAuth } from '../../auth/useAuth'
import { Breadcrumbs, Card, ErrorState, LoadingState, TabNav } from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { patientDisplayName } from '../../lib/format'
import { PatientBanner } from './PatientBanner'
import { PatientContext, RECORD_SECTIONS } from './patientContext'
import './patients.css'

export function PatientRecordLayout() {
  const { patientId = '' } = useParams()
  const { can, canReadClinical } = useAuth()
  const patient = useQuery((s) => patientsApi.get(patientId, s), [patientId])
  const [version, setVersion] = useState(0)
  const recordChanged = useCallback(() => setVersion((v) => v + 1), [])
  const context = useMemo(() => (patient.data ? { patient: patient.data, reload: patient.reload, version, recordChanged } : null),
    [patient.data, patient.reload, version, recordChanged])

  if (patient.error) {
    return (
      <>
        <Breadcrumbs items={[{ label: 'Patients', to: '/patients' }, { label: 'Patient record' }]} />
        <Card>{patient.error.status === 404
          ? <ErrorState error={patient.error} /> : <ErrorState error={patient.error} onRetry={patient.reload} />}</Card>
      </>
    )
  }
  if (!context) return <LoadingState label="Loading patient record…" />

  const base = `/patients/${patientId}`
  const tabs = RECORD_SECTIONS.filter((section) => section.anyOf.some((code) => (section.clinical ? canReadClinical(code) : can(code))))
    .map((section) => ({
    to: section.path ? `${base}/${section.path}` : base, label: section.label, end: section.path === '',
  }))

  return (
    <PatientContext.Provider value={context}>
      <PatientBanner patient={context.patient} version={version} />
      <div className="precord">
        <Breadcrumbs items={[{ label: 'Patients', to: '/patients' }, { label: patientDisplayName(context.patient) }]} />
        <TabNav items={tabs} label="Patient record sections" />
        <div className="precord__section">
          <Outlet />
        </div>
      </div>
    </PatientContext.Provider>
  )
}
