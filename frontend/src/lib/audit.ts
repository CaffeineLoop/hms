/** Human-readable descriptions of audit actions ("POST /api/patients/{patient_id}/observations" -> "Recorded an observation"). */

const EXPLICIT: Record<string, string> = {
  'auth.login': 'Signed in',
  'auth.logout': 'Signed out',
  'auth.logout_all': 'Signed out of all sessions',
  'auth.password_change': 'Changed password',
  'auth.session_revoked': 'Session ended (idle timeout)',
  'ai.analysis': 'Requested an AI analysis',
  'ai.risk_review': 'Reviewed an AI suggestion',
  'user.deactivate': 'Deactivated a user',
  'user.password_reset': 'Reset a user password',
}

const ROUTES: Array<[RegExp, string]> = [
  [/^POST \/api\/patients$/, 'Registered a patient'],
  [/^PATCH \/api\/patients\/\{patient_id\}$/, 'Updated patient details'],
  [/\/encounters$/, 'Opened an encounter'],
  [/\/observations$/, 'Recorded an observation'],
  [/\/conditions$/, 'Documented a condition'],
  [/\/allergies$/, 'Documented an allergy'],
  [/\/clinical-notes$/, 'Wrote a clinical note'],
  [/\/lab-orders$/, 'Ordered a laboratory test'],
  [/\/samples$/, 'Collected a sample'],
  [/\/results$/, 'Entered laboratory results'],
  [/lab-orders\/\{order_id\}\/verify$/, 'Verified laboratory results'],
  [/lab-orders\/\{order_id\}\/release$/, 'Released laboratory results'],
  [/\/reports$/, 'Created a report'],
  [/reports\/\{report_id\}\/release$/, 'Released a report'],
  [/\/prescriptions$/, 'Created a prescription'],
  [/\/activate$/, 'Activated a prescription'],
  [/workflow-tasks$/, 'Created a workflow task'],
  [/workflow-tasks\/\{task_id\}\/complete$/, 'Completed a workflow task'],
  [/\/admissions$/, 'Requested an admission'],
  [/\/appointments$/, 'Booked an appointment'],
  [/^GET /, 'Viewed records'],
]

export function describeAuditAction(action: string): string {
  if (EXPLICIT[action]) return EXPLICIT[action]
  const match = ROUTES.find(([pattern]) => pattern.test(action))
  return match ? match[1] : action
}
