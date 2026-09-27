/**
 * Persistent patient identity banner shown above every section of the patient record, so the clinician always
 * knows whose record is open. Allergies come from the documented allergy records (never inferred).
 */
import { clinicalApi } from '../../api/endpoints'
import type { PatientDetail } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Icon } from '../../components/icons/Icon'
import { Avatar, Badge, StatusBadge } from '../../components/ui'
import { useQuery } from '../../hooks/useQuery'
import { ageFromDob, formatDate, patientDisplayName, sexLabel } from '../../lib/format'
import './PatientBanner.css'

export function PatientBanner({ patient, version = 0 }: { patient: PatientDetail; version?: number }) {
  const { canReadClinical } = useAuth()
  const canAllergies = canReadClinical('allergy.view')
  const allergies = useQuery((s) => clinicalApi.allergies(patient.id, { status: 'ACTIVE', limit: 10 }, s), [patient.id, version],
    { enabled: canAllergies })
  const name = patientDisplayName(patient)
  const inactive = patient.status === 'INACTIVE'

  return (
    <section className={['pbanner', inactive ? 'pbanner--inactive' : ''].join(' ')} aria-label={`Patient: ${name}, ${patient.patient_number}`}>
      <Avatar name={`${patient.first_name} ${patient.last_name}`} size={44} tone="neutral" />
      <div className="pbanner__identity">
        <div className="pbanner__name-row">
          <h1 className="pbanner__name">{name}</h1>
          <StatusBadge status={patient.status} size="sm" />
        </div>
        <dl className="pbanner__facts">
          <div><dt>Patient ID</dt><dd className="mono">{patient.patient_number}</dd></div>
          <div><dt>Age</dt><dd className="tabular">{ageFromDob(patient.date_of_birth)} years</dd></div>
          <div><dt>Sex</dt><dd>{sexLabel(patient.sex)}</dd></div>
          <div><dt>Date of birth</dt><dd className="tabular">{formatDate(`${patient.date_of_birth}T00:00:00`)}</dd></div>
        </dl>
      </div>
      {canAllergies ? (
        <div className="pbanner__allergies" aria-live="polite">
          <span className="pbanner__allergies-label"><Icon name="alert" size={14} /> Allergies</span>
          {allergies.loading ? <span className="text-subtle">Loading…</span>
            : allergies.error ? <span className="text-subtle">Unavailable</span>
              : allergies.data && allergies.data.items.length > 0 ? (
                <span className="pbanner__allergy-list">
                  {allergies.data.items.map((a) => (
                    <Badge key={a.id} tone={a.severity === 'SEVERE' ? 'danger' : 'warning'} size="sm">
                      {a.substance}{a.severity ? ` · ${a.severity.toLowerCase()}` : ''}
                    </Badge>
                  ))}
                  {allergies.data.total > allergies.data.items.length ? <span className="text-subtle">+{allergies.data.total - allergies.data.items.length} more</span> : null}
                </span>
              ) : <span className="pbanner__none">None documented</span>}
        </div>
      ) : null}
      {inactive ? (
        <p className="pbanner__inactive-note">
          <Icon name="info" size={14} /> Inactive record{patient.deactivation_reason ? ` — ${patient.deactivation_reason}` : ''}
        </p>
      ) : null}
    </section>
  )
}
