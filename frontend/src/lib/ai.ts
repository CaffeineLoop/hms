/**
 * AI presentation helpers (UI-5). Evidence source ids are returned by the backend as "<type>:<record id>"
 * (e.g. "observation:<uuid>"). The UI only labels them and links to the record's place in the patient record —
 * it never creates evidence and never fetches raw data on the AI's behalf.
 */

const TYPE_LABEL: Record<string, string> = {
  patient: 'Patient profile', encounter: 'Encounter', observation: 'Observation', condition: 'Condition', allergy: 'Allergy',
  prescription: 'Prescription', lab_result: 'Lab result', report: 'Report', clinical_note: 'Clinical note',
}

/** Where a cited record lives in the patient record, and the read permission that page needs. */
const TYPE_ROUTE: Partial<Record<string, (patientId: string, id: string) => { to: string; permission: string }>> = {
  patient: (p) => ({ to: `/patients/${p}`, permission: 'patient.view' }),
  encounter: (p, id) => ({ to: `/patients/${p}/encounters/${id}`, permission: 'encounter.view' }),
  observation: (p) => ({ to: `/patients/${p}/vitals`, permission: 'observation.view' }),
  condition: (p) => ({ to: `/patients/${p}/conditions`, permission: 'condition.view' }),
  allergy: (p) => ({ to: `/patients/${p}/allergies`, permission: 'allergy.view' }),
  prescription: (p, id) => ({ to: `/patients/${p}/prescriptions/${id}`, permission: 'prescription.view' }),
  lab_result: (p) => ({ to: `/patients/${p}/diagnostics`, permission: 'lab.view' }),
  report: (p, id) => ({ to: `/patients/${p}/diagnostics/reports/${id}`, permission: 'report.view' }),
  clinical_note: (p) => ({ to: `/patients/${p}/notes`, permission: 'clinical_note.view' }),
}

export interface EvidenceRef {
  sourceId: string
  type: string
  label: string
  shortId: string
  link: { to: string; permission: string } | null
}

export function evidenceRef(sourceId: string, patientId: string): EvidenceRef {
  const [type, id = ''] = sourceId.split(':', 2)
  const route = TYPE_ROUTE[type]
  return {
    sourceId, type, label: TYPE_LABEL[type] ?? type, shortId: id.slice(0, 8),
    link: route && id ? route(patientId, id) : null,
  }
}

/** Plain-language labels for backend reason codes (the backend message is always shown alongside). */
export const REASON_LABEL: Record<string, string> = {
  insufficient_data: 'Insufficient data',
  insufficient_recent_data: 'Insufficient recent data',
  model_abstained: 'The assistant abstained',
  invalid_model_output: 'Model output failed validation',
  model_unavailable: 'AI model unavailable',
  missing_permission: 'Missing permission',
  patient_out_of_scope: 'Patient outside your access',
  human_user_required: 'A signed-in staff member is required',
}

export function reasonLabel(code: string | null): string | null {
  if (!code) return null
  return REASON_LABEL[code] ?? code.replace(/_/g, ' ')
}
