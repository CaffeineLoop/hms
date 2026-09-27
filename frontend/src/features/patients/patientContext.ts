/** The patient whose record is open. Provided by PatientRecordLayout to every record section. */
import { createContext, useContext } from 'react'
import type { PatientDetail } from '../../api/types'

export interface PatientRecordContext {
  patient: PatientDetail
  reload: () => void
  /** UI-3: bumped after a successful write so record-wide views (e.g. the banner allergies) re-fetch from the API. */
  version: number
  recordChanged: () => void
}

export const PatientContext = createContext<PatientRecordContext | null>(null)

export function usePatientRecord(): PatientRecordContext {
  const context = useContext(PatientContext)
  if (!context) throw new Error('usePatientRecord must be used inside PatientRecordLayout')
  return context
}

/**
 * Record sections and the permissions each requires (backend-enforced). `anyOf`: any one grants the section.
 * Clinical sections follow the backend clinical-read rule (permission + patient.view at ALL scope); the Overview
 * only needs patient.view.
 */
export const RECORD_SECTIONS = [
  { path: '', label: 'Overview', anyOf: ['patient.view'], clinical: false },
  { path: 'timeline', label: 'Timeline', anyOf: ['timeline.view'], clinical: true },
  { path: 'encounters', label: 'Encounters', anyOf: ['encounter.view'], clinical: true },
  { path: 'vitals', label: 'Vitals & observations', anyOf: ['observation.view'], clinical: true },
  { path: 'conditions', label: 'Conditions', anyOf: ['condition.view'], clinical: true },
  { path: 'allergies', label: 'Allergies', anyOf: ['allergy.view'], clinical: true },
  { path: 'notes', label: 'Clinical notes', anyOf: ['clinical_note.view'], clinical: true },
  { path: 'diagnostics', label: 'Diagnostics', anyOf: ['lab.view', 'report.view'], clinical: true },
  { path: 'prescriptions', label: 'Prescriptions', anyOf: ['prescription.view'], clinical: true },
  // UI-5: AI suggestions for review (backend also requires patient.view at ALL scope for any AI access)
  { path: 'ai', label: 'AI analysis', anyOf: ['ai.analysis', 'ai.review'], clinical: true },
] as const
