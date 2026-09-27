/** The existing HMS endpoints used by the UI (no new backend endpoints). */
import { api, apiRequest } from './client'
import type {
  AIAnalysisResult, AICapabilities, Admission, Allergy, Appointment, AuditEvent, AuditEventDetail, ClinicalNote, Department, PermissionInfo, Role, UserAccount, Condition, Encounter, Health, LabOrder, Me, Observation, Page, PatientCreate, PatientDetail,
  PatientList, Prescription, Report, RiskAnalysis, RiskAnalysisSummary, StaffMember, Timeline, TimelineEventType, TokenResponse, WorkflowTask,
} from './types'

type PageQuery = { limit?: number; offset?: number }

export const authApi = {
  login: (username: string, password: string) =>
    apiRequest<TokenResponse>('POST', '/api/auth/login', { body: { username, password }, auth: false }),
  me: (signal?: AbortSignal) => api.get<Me>('/api/auth/me', undefined, signal),
  logout: () => api.post<void>('/api/auth/logout'),
  /** Revokes every session of the signed-in user, including this one. */
  logoutAll: () => api.post<void>('/api/auth/logout-all'),
  /** Other sessions are revoked by the backend; this one stays valid. */
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<void>('/api/auth/change-password', { current_password: currentPassword, new_password: newPassword }),
}

export const systemApi = {
  health: (signal?: AbortSignal) => apiRequest<Health>('GET', '/health', { signal, auth: false }),
}

/** Stage 1 — /api/patients */
export const patientsApi = {
  list: (query: PageQuery & { q?: string; status?: string }, signal?: AbortSignal) =>
    api.get<PatientList>('/api/patients', query, signal),
  get: (patientId: string, signal?: AbortSignal) => api.get<PatientDetail>(`/api/patients/${patientId}`, undefined, signal),
  create: (data: PatientCreate) => api.post<PatientDetail>('/api/patients', data),
}

/** Stage 2 — clinical records and the patient timeline (read-only in UI-1). */
const P = (patientId: string) => `/api/patients/${patientId}`
export const clinicalApi = {
  encounters: (patientId: string, query: PageQuery & { status?: string; encounter_type?: string }, signal?: AbortSignal) =>
    api.get<Page<Encounter>>(`${P(patientId)}/encounters`, query, signal),
  encounter: (patientId: string, encounterId: string, signal?: AbortSignal) =>
    api.get<Encounter>(`${P(patientId)}/encounters/${encounterId}`, undefined, signal),
  observations: (patientId: string, query: PageQuery & { code?: string; encounter_id?: string }, signal?: AbortSignal) =>
    api.get<Page<Observation>>(`${P(patientId)}/observations`, query, signal),
  conditions: (patientId: string, query: PageQuery & { status?: string }, signal?: AbortSignal) =>
    api.get<Page<Condition>>(`${P(patientId)}/conditions`, query, signal),
  allergies: (patientId: string, query: PageQuery & { status?: string }, signal?: AbortSignal) =>
    api.get<Page<Allergy>>(`${P(patientId)}/allergies`, query, signal),
  notes: (patientId: string, query: PageQuery & { note_type?: string; encounter_id?: string }, signal?: AbortSignal) =>
    api.get<Page<ClinicalNote>>(`${P(patientId)}/clinical-notes`, query, signal),
  timeline: (patientId: string, query: PageQuery & { types?: readonly TimelineEventType[]; order?: 'asc' | 'desc' },
    signal?: AbortSignal) => api.get<Timeline>(`${P(patientId)}/timeline`, query, signal),
}

/**
 * Stage 3 — laboratory, reports and prescriptions (read-only in UI-2). Lab orders embed their samples and results.
 * Records are also addressable by id; those reads are authorized by the backend (clinical-read rule).
 */
export const diagnosticsApi = {
  labOrders: (patientId: string, query: PageQuery & { status?: string }, signal?: AbortSignal) =>
    api.get<Page<LabOrder>>(`${P(patientId)}/lab-orders`, query, signal),
  labOrder: (orderId: string, signal?: AbortSignal) => api.get<LabOrder>(`/api/lab-orders/${orderId}`, undefined, signal),
  reports: (patientId: string, query: PageQuery & { status?: string; report_type?: string }, signal?: AbortSignal) =>
    api.get<Page<Report>>(`${P(patientId)}/reports`, query, signal),
  report: (reportId: string, signal?: AbortSignal) => api.get<Report>(`/api/reports/${reportId}`, undefined, signal),
}

export const prescriptionsApi = {
  list: (patientId: string, query: PageQuery & { status?: string }, signal?: AbortSignal) =>
    api.get<Page<Prescription>>(`${P(patientId)}/prescriptions`, query, signal),
  get: (prescriptionId: string, signal?: AbortSignal) =>
    api.get<Prescription>(`/api/prescriptions/${prescriptionId}`, undefined, signal),
}

/** Stage 4 — staff directory (clinician names for attribution; staff/department pickers for assignments). */
export const staffApi = {
  get: (staffId: string, signal?: AbortSignal) => api.get<StaffMember>(`/api/staff/${staffId}`, undefined, signal),
  list: (query: PageQuery & { department_id?: string; status?: string; q?: string; designation?: string }, signal?: AbortSignal) =>
    api.get<Page<StaffMember>>('/api/staff', query, signal),
  departments: (query: PageQuery & { status?: string }, signal?: AbortSignal) =>
    api.get<Page<Department>>('/api/departments', query, signal),
}

type Window = { scheduled_from?: string; scheduled_to?: string }

/** Stage 4 — appointments, admissions and workflow tasks. Lifecycle actions are the backend action endpoints. */
export const workflowApi = {
  tasks: (query: PageQuery & { status?: string; priority?: string; assigned_staff_id?: string; patient_id?: string;
    workflow_type?: string }, signal?: AbortSignal) => api.get<Page<WorkflowTask>>('/api/workflow-tasks', query, signal),
  admissions: (query: PageQuery & { status?: string; department_id?: string }, signal?: AbortSignal) =>
    api.get<Page<Admission>>('/api/admissions', query, signal),
  appointments: (query: PageQuery & Window & { status?: string; patient_id?: string; staff_id?: string; department_id?: string },
    signal?: AbortSignal) => api.get<Page<Appointment>>('/api/appointments', query, signal),

  bookAppointment: (patientId: string, body: unknown) => api.post<Appointment>(`${P(patientId)}/appointments`, body),
  appointmentAction: (id: string, action: AppointmentAction, body?: unknown) =>
    api.post<Appointment>(`/api/appointments/${id}/${action}`, body),

  requestAdmission: (patientId: string, body: unknown) => api.post<Admission>(`${P(patientId)}/admissions`, body),
  admissionAction: (id: string, action: AdmissionAction, body?: unknown) =>
    api.post<Admission>(`/api/admissions/${id}/${action}`, body),

  createTask: (body: unknown) => api.post<WorkflowTask>('/api/workflow-tasks', body),
  taskAction: (id: string, action: TaskAction, body?: unknown) => api.post<WorkflowTask>(`/api/workflow-tasks/${id}/${action}`, body),
}

export type AppointmentAction = 'confirm' | 'check-in' | 'start-consultation' | 'complete' | 'no-show' | 'cancel'
export type AdmissionAction = 'approve' | 'admit' | 'transfer' | 'discharge' | 'cancel'
export type TaskAction = 'assign' | 'start' | 'complete' | 'cancel'
export type EncounterAction = 'start' | 'finish' | 'cancel'

/**
 * UI-3 — clinical documentation writes (existing Stage 2 endpoints). Authorship is never sent: the backend binds the
 * author/recorder to the signed-in user (staff member).
 */
export const clinicalWriteApi = {
  createEncounter: (patientId: string, body: unknown) => api.post<Encounter>(`${P(patientId)}/encounters`, body),
  encounterAction: (encounterId: string, action: EncounterAction, body?: unknown) =>
    api.post<Encounter>(`/api/encounters/${encounterId}/${action}`, body),
  createObservation: (patientId: string, body: unknown) => api.post<Observation>(`${P(patientId)}/observations`, body),
  createNote: (patientId: string, body: unknown) => api.post<ClinicalNote>(`${P(patientId)}/clinical-notes`, body),
  createCondition: (patientId: string, body: unknown) => api.post<Condition>(`${P(patientId)}/conditions`, body),
  updateCondition: (conditionId: string, body: unknown) => api.patch<Condition>(`/api/conditions/${conditionId}`, body),
  createAllergy: (patientId: string, body: unknown) => api.post<Allergy>(`${P(patientId)}/allergies`, body),
  updateAllergy: (allergyId: string, body: unknown) => api.patch<Allergy>(`/api/allergies/${allergyId}`, body),
}

export interface AuditQuery extends PageQuery {
  action?: string
  outcome?: string
  actor_user_id?: string
  resource_type?: string
  resource_id?: string
  patient_id?: string
  occurred_from?: string
  occurred_to?: string
}

/** Stage 6 audit trail — read-only (there is no write API). */
export const auditApi = {
  events: (query: { limit?: number }, signal?: AbortSignal) => api.get<Page<AuditEvent>>('/api/audit-events', query, signal),
  search: (query: AuditQuery, signal?: AbortSignal) => api.get<Page<AuditEventDetail>>('/api/audit-events', { ...query }, signal),
  get: (eventId: string, signal?: AbortSignal) => api.get<AuditEventDetail>(`/api/audit-events/${eventId}`, undefined, signal),
}

/** Stage 5 access administration: users, roles, permission grants. Anti-escalation rules are enforced by the backend. */
export const accessApi = {
  users: (query: PageQuery & { q?: string; status?: string }, signal?: AbortSignal) =>
    api.get<Page<UserAccount>>('/api/users', query, signal),
  user: (userId: string, signal?: AbortSignal) => api.get<UserAccount>(`/api/users/${userId}`, undefined, signal),
  userAction: (userId: string, action: 'deactivate' | 'reactivate') => api.post<UserAccount>(`/api/users/${userId}/${action}`),
  resetPassword: (userId: string, newPassword: string) =>
    api.post<UserAccount>(`/api/users/${userId}/reset-password`, { new_password: newPassword }),
  assignRole: (userId: string, roleId: string) => api.post<UserAccount>(`/api/users/${userId}/roles`, { role_id: roleId }),
  removeRole: (userId: string, roleId: string) => apiRequest<UserAccount>('DELETE', `/api/users/${userId}/roles/${roleId}`),

  roles: (query: PageQuery & { status?: string }, signal?: AbortSignal) => api.get<Page<Role>>('/api/roles', query, signal),
  role: (roleId: string, signal?: AbortSignal) => api.get<Role>(`/api/roles/${roleId}`, undefined, signal),
  createRole: (body: { name: string; description: string | null }) => api.post<Role>('/api/roles', body),
  updateRole: (roleId: string, body: { name?: string; description?: string | null }) => api.patch<Role>(`/api/roles/${roleId}`, body),
  roleAction: (roleId: string, action: 'deactivate' | 'reactivate') => api.post<Role>(`/api/roles/${roleId}/${action}`),
  grant: (roleId: string, code: string, scope: 'ALL' | 'OWN') => api.post<Role>(`/api/roles/${roleId}/permissions`, { code, scope }),
  revoke: (roleId: string, code: string) => apiRequest<Role>('DELETE', `/api/roles/${roleId}/permissions/${code}`),
  permissions: (signal?: AbortSignal) => api.get<PermissionInfo[]>('/api/permissions', undefined, signal),
}

/**
 * Stages 7-10 AI assistant (UI-5). Read-only analysis; stored four-day risk analyses are AI suggestions awaiting
 * human review. The only write is the review decision, which changes the AI record only — never clinical data.
 */
export const aiApi = {
  riskAnalyses: (query: { review_status?: string; limit?: number }, signal?: AbortSignal) =>
    api.get<Page<RiskAnalysisSummary>>('/api/ai/risk-analyses', query, signal),
  capabilities: (signal?: AbortSignal) => api.get<AICapabilities>('/api/ai/capabilities', undefined, signal),
  /** Runs the bounded four-day risk analysis for one patient (reference time defaults to now on the backend). */
  analyzeFourDayRisk: (patientId: string) =>
    api.post<AIAnalysisResult>('/api/ai/analyses', { patient_id: patientId, analysis_type: 'FOUR_DAY_RISK' }),
  list: (query: PageQuery & { patient_id?: string; review_status?: string }, signal?: AbortSignal) =>
    api.get<Page<RiskAnalysis>>('/api/ai/risk-analyses', query, signal),
  get: (analysisId: string, signal?: AbortSignal) => api.get<RiskAnalysis>(`/api/ai/risk-analyses/${analysisId}`, undefined, signal),
  review: (analysisId: string, decision: 'ACKNOWLEDGED' | 'DISMISSED', comment: string | null) =>
    api.post<RiskAnalysis>(`/api/ai/risk-analyses/${analysisId}/review`, { decision, comment }),
}
