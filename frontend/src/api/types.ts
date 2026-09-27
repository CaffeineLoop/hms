/** Types mirroring the existing FastAPI response schemas (app/schemas/*). Read-only contracts. */

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type Scope = 'ALL' | 'OWN'

export interface StaffSummary {
  id: string
  employee_code: string
  full_name: string
  designation: string
  department_id: string
}

export interface Me {
  user_id: string
  username: string
  staff: StaffSummary
  roles: string[]
  is_superuser: boolean
  permissions: Grant[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_at: string
  user: Me
}

export interface Health {
  status: 'ok'
  app: string
  environment: string
}

export type Sex = 'MALE' | 'FEMALE' | 'OTHER' | 'UNKNOWN'

export interface Patient {
  id: string
  patient_number: string
  first_name: string
  middle_name: string | null
  last_name: string
  date_of_birth: string
  sex: Sex
  phone: string | null
  status: string
  created_at: string
}

export type TaskStatus = 'OPEN' | 'ASSIGNED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
export type TaskPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT'

export interface WorkflowTask {
  id: string
  patient_id: string | null
  department_id: string | null
  workflow_type: string
  title: string
  description: string | null
  priority: TaskPriority
  status: TaskStatus
  due_at: string | null
  created_by_staff_id: string | null
  assigned_staff_id: string | null
  assigned_at: string | null
  started_at: string | null
  completed_at: string | null
  completion_notes: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string
  updated_at: string
}

export type AuditOutcome = 'SUCCESS' | 'FAILURE' | 'DENIED'

export interface AuditEvent {
  id: string
  occurred_at: string
  action: string
  outcome: AuditOutcome
  actor_username: string | null
  resource_type: string | null
  patient_id: string | null
}

/** Full audit record (GET /api/audit-events, /api/audit-events/{id}). Read-only. */
export interface AuditEventDetail extends AuditEvent {
  request_id: string | null
  actor_user_id: string | null
  actor_staff_id: string | null
  session_id: string | null
  resource_id: string | null
  http_method: string | null
  route: string | null
  status_code: number | null
  client_ip: string | null
  user_agent: string | null
  details: Record<string, unknown>
}

// ---------------------------------------------------------------- Stage 5 access administration (UI-4)

export type RecordStatus = 'ACTIVE' | 'INACTIVE'

export interface Grant {
  code: string
  scope: Scope
}

export interface RoleSummary {
  id: string
  name: string
  status: RecordStatus
  is_superuser: boolean
}

export interface UserAccount {
  id: string
  staff_id: string
  username: string
  status: RecordStatus
  password_changed_at: string
  last_login_at: string | null
  deactivated_at: string | null
  roles: RoleSummary[]
  created_at: string
  updated_at: string
}

export interface Role {
  id: string
  name: string
  description: string | null
  status: RecordStatus
  is_superuser: boolean
  permissions: Grant[]
  user_count: number
  created_at: string
  updated_at: string
}

export interface PermissionInfo {
  code: string
  description: string
}

// ---------------------------------------------------------------- Stages 7-10 AI (UI-5): read-only, review-only

export type ReviewPriority = 'LOW' | 'MODERATE' | 'HIGH'
export type RiskReviewStatus = 'PENDING_REVIEW' | 'ACKNOWLEDGED' | 'DISMISSED'
export type AnalysisStatus = 'COMPLETED' | 'ABSTAINED' | 'REFUSED'

export interface EvidenceCitation { source_id: string; relevance: string }

export interface RiskSignal {
  signal_id: string
  rule_id: string
  category: string
  priority: ReviewPriority
  title: string
  detail: string
  evidence: string[]
}

/** The model's validated four-day output (explains the deterministic signals; cannot add or re-grade them). */
export interface ModelRiskOutput {
  status: 'ANALYSIS' | 'ABSTAIN'
  analysis_type: 'FOUR_DAY_RISK'
  patient_reference: string
  reference_at: string
  horizon_start: string
  horizon_end: string
  analysis_horizon_days: 4
  summary: string
  risk_signals: Array<{ signal_id: string; category: string; priority: ReviewPriority; explanation: string; evidence: string[] }>
  observed_trends: Array<{ description: string; evidence: string[] }>
  evidence: EvidenceCitation[]
  limitations: string[]
  precautionary_suggestions: string[]
  requires_human_review: boolean
  abstain_reason: string | null
}

/** A stored four-day risk analysis: an AI suggestion awaiting human review. Not a clinical record. */
export interface RiskAnalysis {
  id: string
  patient_id: string
  status: AnalysisStatus
  reason_code: string | null
  trigger: 'MANUAL' | 'EVENT'
  trigger_event: string | null
  trigger_source_id: string | null
  requested_by_user_id: string
  requested_by_staff_id: string
  reference_at: string
  horizon_start: string
  horizon_end: string
  analysis_horizon_days: number
  ruleset_id: string
  ruleset_version: string
  ruleset_validated: boolean
  signals: RiskSignal[]
  data_gaps: string[]
  max_priority: ReviewPriority | null
  output: ModelRiskOutput | null
  provider: string
  model: string
  requires_human_review: boolean
  review_status: RiskReviewStatus
  reviewed_by_user_id: string | null
  reviewed_by_staff_id: string | null
  reviewed_at: string | null
  review_comment: string | null
  created_at: string
  disclaimer: string
}

/** POST /api/ai/analyses response (FOUR_DAY_RISK fields used by the UI). */
export interface AIAnalysisResult {
  request_id: string
  status: AnalysisStatus
  reason_code: string | null
  message: string
  patient_id: string
  analysis_type: string
  risk: { risk_analysis_id: string | null; review_status: RiskReviewStatus | null; data_gaps: string[] } | null
  tools_used: string[]
  tools_withheld: string[]
  evidence_count: number
  model: { provider: string; model: string } | null
  generated_at: string
  disclaimer: string
}

export interface AICapabilities {
  enabled: boolean
  provider: string
  model: string
  analysis_types: string[]
  tools: Array<{ name: string; description: string; required_permission: string; read_only: boolean; available_to_you: boolean }>
}

export interface RiskAnalysisSummary {
  id: string
  patient_id: string
  status: 'COMPLETED' | 'ABSTAINED'
  reference_at: string
  horizon_end: string
  max_priority: 'LOW' | 'MODERATE' | 'HIGH' | null
  review_status: 'PENDING_REVIEW' | 'ACKNOWLEDGED' | 'DISMISSED'
  created_at: string
}

// ---------------------------------------------------------------- UI-1: patients & clinical records

export type PatientStatus = 'ACTIVE' | 'INACTIVE'

/** GET /api/patients returns items + total only. */
export interface PatientList {
  items: PatientDetail[]
  total: number
}

/** PatientRead (full record returned to holders of patient.view). */
export interface PatientDetail extends Patient {
  email: string | null
  address_line1: string | null
  address_line2: string | null
  city: string | null
  state_province: string | null
  postal_code: string | null
  country: string | null
  emergency_contact_name: string | null
  emergency_contact_relationship: string | null
  emergency_contact_phone: string | null
  status: PatientStatus
  deactivated_at: string | null
  deactivation_reason: string | null
  updated_at: string
}

/** PatientCreate (POST /api/patients). */
export interface PatientCreate {
  first_name: string
  middle_name?: string | null
  last_name: string
  date_of_birth: string
  sex: Sex
  phone?: string | null
  email?: string | null
  address_line1?: string | null
  address_line2?: string | null
  city?: string | null
  state_province?: string | null
  postal_code?: string | null
  country?: string | null
  emergency_contact_name?: string | null
  emergency_contact_relationship?: string | null
  emergency_contact_phone?: string | null
}

export type EncounterType = 'OPD' | 'EMERGENCY' | 'INPATIENT' | 'FOLLOW_UP'
export type EncounterStatus = 'PLANNED' | 'IN_PROGRESS' | 'FINISHED' | 'CANCELLED'

export interface Encounter {
  id: string
  patient_id: string
  encounter_type: EncounterType
  status: EncounterStatus
  reason: string
  start_at: string
  end_at: string | null
  summary: string | null
  cancellation_reason: string | null
  attending_staff_id: string | null
  created_at: string
  updated_at: string
}

export interface Observation {
  id: string
  patient_id: string
  encounter_id: string | null
  code: string
  display: string
  code_system: string | null
  system_code: string | null
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  effective_at: string
  notes: string | null
  created_at: string
}

export type ConditionStatus = 'SUSPECTED' | 'ACTIVE' | 'RESOLVED' | 'HISTORICAL'

export interface Condition {
  id: string
  patient_id: string
  encounter_id: string | null
  name: string
  code_system: string | null
  code: string | null
  status: ConditionStatus
  onset_at: string | null
  resolved_at: string | null
  recorded_at: string
  notes: string | null
  created_at: string
}

export type AllergyStatus = 'ACTIVE' | 'INACTIVE' | 'RESOLVED'
export type AllergySeverity = 'MILD' | 'MODERATE' | 'SEVERE'

export interface Allergy {
  id: string
  patient_id: string
  encounter_id: string | null
  substance: string
  code_system: string | null
  code: string | null
  category: 'FOOD' | 'MEDICATION' | 'ENVIRONMENT' | 'BIOLOGIC' | null
  reaction: string | null
  severity: AllergySeverity | null
  status: AllergyStatus
  onset_at: string | null
  recorded_at: string
  notes: string | null
  created_at: string
}

export type NoteType = 'PROGRESS' | 'HISTORY_AND_PHYSICAL' | 'CONSULTATION' | 'NURSING' | 'PROCEDURE' |
  'DISCHARGE_SUMMARY' | 'OTHER'

export interface ClinicalNote {
  id: string
  patient_id: string
  encounter_id: string
  note_type: NoteType
  author_name: string
  author_staff_id: string | null
  content: string
  authored_at: string
  created_at: string
}

// ---------------------------------------------------------------- Stage 3: laboratory, reports, prescriptions

export type LabOrderStatus = 'ORDERED' | 'SAMPLE_COLLECTED' | 'PROCESSING' | 'RESULT_ENTERED' | 'VERIFIED' | 'RELEASED' |
  'CANCELLED'
export type LabPriority = 'ROUTINE' | 'URGENT' | 'STAT'
export type ResultInterpretation = 'NORMAL' | 'LOW' | 'HIGH' | 'CRITICAL_LOW' | 'CRITICAL_HIGH' | 'ABNORMAL'

export interface LabSample {
  id: string
  patient_id: string
  lab_order_id: string
  accession_number: string
  specimen_type: string
  collected_at: string
  collected_by: string
  collected_by_staff_id: string | null
  notes: string | null
  created_at: string
}

export interface LabResult {
  id: string
  patient_id: string
  lab_order_id: string
  analyte_code: string
  analyte_name: string
  code_system: string | null
  system_code: string | null
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  reference_low: number | null
  reference_high: number | null
  reference_text: string | null
  interpretation: ResultInterpretation | null
  resulted_at: string
  entered_by: string
  entered_by_staff_id: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface LabOrder {
  id: string
  patient_id: string
  encounter_id: string
  order_number: string
  test_code: string
  test_name: string
  code_system: string | null
  system_code: string | null
  priority: LabPriority
  status: LabOrderStatus
  clinical_indication: string | null
  ordered_by: string
  ordered_by_staff_id: string | null
  ordered_at: string
  processing_started_at: string | null
  results_entered_at: string | null
  verified_by: string | null
  verified_by_staff_id: string | null
  verified_at: string | null
  released_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string
  updated_at: string
  samples: LabSample[]
  results: LabResult[]
}

export type ReportStatus = 'DRAFT' | 'VERIFIED' | 'RELEASED' | 'CANCELLED'
export type ReportType = 'LABORATORY' | 'IMAGING' | 'CONSULTATION' | 'DISCHARGE' | 'PROCEDURE' | 'OTHER'

export interface Report {
  id: string
  patient_id: string
  encounter_id: string | null
  lab_order_id: string | null
  report_type: ReportType
  title: string
  code_system: string | null
  code: string | null
  status: ReportStatus
  effective_at: string
  requested_by: string | null
  requested_by_staff_id: string | null
  requested_at: string | null
  author_name: string
  author_staff_id: string | null
  content: string | null
  conclusion: string | null
  verified_by: string | null
  verified_by_staff_id: string | null
  verified_at: string | null
  released_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string
  updated_at: string
}

export type PrescriptionStatus = 'DRAFT' | 'ACTIVE' | 'ON_HOLD' | 'COMPLETED' | 'CANCELLED'

export interface PrescriptionItem {
  id: string
  prescription_id: string
  line_number: number
  medicine_name: string
  code_system: string | null
  code: string | null
  dose_value: number
  dose_unit: string
  route: string
  frequency: string
  duration_value: number | null
  duration_unit: 'DAYS' | 'WEEKS' | 'MONTHS' | null
  quantity: number | null
  quantity_unit: string | null
  instructions: string | null
  created_at: string
}

export interface Prescription {
  id: string
  patient_id: string
  encounter_id: string
  prescription_number: string
  prescriber_name: string
  prescriber_staff_id: string | null
  status: PrescriptionStatus
  prescribed_at: string
  activated_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  notes: string | null
  items: PrescriptionItem[]
  created_at: string
  updated_at: string
}

export type TimelineEventType = 'encounter' | 'observation' | 'condition' | 'allergy' | 'clinical_note' | 'lab_order' |
  'lab_sample' | 'lab_result' | 'report' | 'prescription' | 'appointment' | 'admission' | 'admission_transfer' |
  'workflow_task'

export interface TimelineEvent {
  event_type: TimelineEventType
  occurred_at: string
  record_id: string
  encounter_id: string | null
  title: string
  status: string | null
  data: Record<string, unknown>
}

export interface Timeline {
  patient_id: string
  items: TimelineEvent[]
  total: number
  limit: number
  offset: number
  order: 'asc' | 'desc'
}

export interface StaffMember {
  id: string
  employee_code: string
  full_name: string
  designation: string
  department_id: string
  status: string
  phone?: string | null
  email?: string | null
}

export interface Department {
  id: string
  name: string
  description: string | null
  status: string
}

// ---------------------------------------------------------------- Stage 4 workflow (UI-3)

export type AppointmentStatus = 'REQUESTED' | 'CONFIRMED' | 'CHECKED_IN' | 'IN_CONSULTATION' | 'COMPLETED' | 'CANCELLED' |
  'NO_SHOW'

export interface Appointment {
  id: string
  patient_id: string
  department_id: string
  staff_id: string | null
  encounter_id: string | null
  reason: string
  scheduled_start: string
  duration_minutes: number
  status: AppointmentStatus
  notes: string | null
  confirmed_at: string | null
  checked_in_at: string | null
  consultation_started_at: string | null
  completed_at: string | null
  no_show_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string
  updated_at: string
}

export type AdmissionStatus = 'REQUESTED' | 'APPROVED' | 'ADMITTED' | 'TRANSFERRED' | 'DISCHARGED' | 'CANCELLED'

export interface AdmissionTransfer {
  id: string
  from_department_id: string
  to_department_id: string
  from_bed: string | null
  to_bed: string | null
  reason: string
  transferred_at: string
  transferred_by_staff_id: string | null
}

export interface Admission {
  id: string
  patient_id: string
  department_id: string
  bed: string | null
  encounter_id: string | null
  admission_type: 'ELECTIVE' | 'EMERGENCY'
  reason: string
  status: AdmissionStatus
  requested_by_staff_id: string
  requested_at: string
  approved_by_staff_id: string | null
  approved_at: string | null
  attending_staff_id: string | null
  admitted_at: string | null
  discharged_at: string | null
  discharge_disposition: string | null
  discharge_summary: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string
  updated_at: string
  transfers: AdmissionTransfer[]
}
