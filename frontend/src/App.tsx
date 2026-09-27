import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/useAuth'
import { AppShell } from './components/shell/AppShell'
import { ALL_NAV_ITEMS } from './components/shell/navigation'
import { LoadingState } from './components/ui'
import {
  ClinicalRecordsPage, DiagnosticsModulePage, PatientListPage, PrescriptionsModulePage,
} from './features/patients/PatientListPage'
import { PatientRecordLayout } from './features/patients/PatientRecordLayout'
import { RegisterPatientPage } from './features/patients/RegisterPatientPage'
import { SectionGuard } from './features/patients/SectionGuard'
import {
  NewAllergyPage, NewConditionPage, NewEncounterPage, NewNotePage, RecordVitalsPage,
} from './features/patients/writes/ClinicalForms'
import { EncounterDetailPage, EncountersSection } from './features/patients/sections/EncountersSection'
import { OverviewSection } from './features/patients/sections/OverviewSection'
import { DiagnosticsSection, LabOrderDetailPage, ReportDetailPage } from './features/patients/sections/DiagnosticsSection'
import { PrescriptionDetailPage, PrescriptionsSection } from './features/patients/sections/PrescriptionsSection'
import { AllergiesSection, ConditionsSection, NotesSection } from './features/patients/sections/RecordSections'
import { TimelineSection } from './features/patients/sections/TimelineSection'
import { VitalsSection } from './features/patients/sections/VitalsSection'
import {
  AdmissionsPanel, AppointmentsPanel, BookAppointmentPage, NewTaskPage, RequestAdmissionPage, TasksPanel, WorkflowsIndex,
  WorkflowsLayout, AreaGuard,
} from './features/workflows/WorkflowsPage'
import { AccountPage } from './features/account/AccountPage'
import { StaffPage } from './features/staff/StaffPage'
import { AiModulePage, PatientAiSection, RiskAnalysisDetailPage } from './features/ai/AiPages'
import { AdminIndex, AdminLayout } from './features/admin/AdminLayout'
import { AuditPage } from './features/admin/AuditPage'
import { PermissionsPage, RoleDetailPage, RolesPage } from './features/admin/RolesPages'
import { UserDetailPage, UsersPage } from './features/admin/UsersPages'
import { DashboardPage } from './pages/DashboardPage'
import { DesignSystemPage } from './pages/DesignSystemPage'
import { LoginPage } from './pages/LoginPage'
import { ModulePage } from './pages/ModulePage'
import { NotFoundPage } from './pages/NotFoundPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'restoring') {
    return <div className="boot"><LoadingState label="Restoring your session…" /></div>
  }
  if (status === 'signed-out') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<DashboardPage />} />
            {/* UI-1: patients & clinical records */}
            <Route path="patients" element={<PatientListPage />} />
            <Route path="patients/new" element={<RegisterPatientPage />} />
            <Route path="patients/:patientId" element={<PatientRecordLayout />}>
              <Route index element={<OverviewSection />} />
              <Route path="timeline" element={<SectionGuard permission="timeline.view"><TimelineSection /></SectionGuard>} />
              <Route path="encounters" element={<SectionGuard permission="encounter.view"><EncountersSection /></SectionGuard>} />
              {/* UI-3: clinical documentation writes (read access to the section + the write permission) */}
              <Route path="encounters/new" element={<SectionGuard permission="encounter.view"><NewEncounterPage /></SectionGuard>} />
              <Route path="vitals/new" element={<SectionGuard permission="observation.view"><RecordVitalsPage /></SectionGuard>} />
              <Route path="notes/new" element={<SectionGuard permission="clinical_note.view"><NewNotePage /></SectionGuard>} />
              <Route path="conditions/new" element={<SectionGuard permission="condition.view"><NewConditionPage /></SectionGuard>} />
              <Route path="allergies/new" element={<SectionGuard permission="allergy.view"><NewAllergyPage /></SectionGuard>} />
              <Route path="encounters/:encounterId" element={<SectionGuard permission="encounter.view"><EncounterDetailPage /></SectionGuard>} />
              <Route path="vitals" element={<SectionGuard permission="observation.view"><VitalsSection /></SectionGuard>} />
              <Route path="conditions" element={<SectionGuard permission="condition.view"><ConditionsSection /></SectionGuard>} />
              <Route path="allergies" element={<SectionGuard permission="allergy.view"><AllergiesSection /></SectionGuard>} />
              <Route path="notes" element={<SectionGuard permission="clinical_note.view"><NotesSection /></SectionGuard>} />
              {/* UI-2: diagnostics & prescriptions (read-only) */}
              <Route path="diagnostics" element={<SectionGuard permission={['lab.view', 'report.view']}><DiagnosticsSection /></SectionGuard>} />
              <Route path="diagnostics/lab-orders/:orderId" element={<SectionGuard permission="lab.view"><LabOrderDetailPage /></SectionGuard>} />
              <Route path="diagnostics/reports/:reportId" element={<SectionGuard permission="report.view"><ReportDetailPage /></SectionGuard>} />
              <Route path="prescriptions" element={<SectionGuard permission="prescription.view"><PrescriptionsSection /></SectionGuard>} />
              {/* UI-5: AI suggestions for clinician review (read-only; backend enforces ai.* and patient scope) */}
              <Route path="ai" element={<SectionGuard permission={['ai.analysis', 'ai.review']}><PatientAiSection /></SectionGuard>} />
              <Route path="ai/:analysisId" element={<SectionGuard permission={['ai.analysis', 'ai.review']}><RiskAnalysisDetailPage /></SectionGuard>} />
              <Route path="prescriptions/:prescriptionId" element={<SectionGuard permission="prescription.view"><PrescriptionDetailPage /></SectionGuard>} />
            </Route>
            <Route path="clinical" element={<ClinicalRecordsPage />} />
            <Route path="diagnostics" element={<DiagnosticsModulePage />} />
            <Route path="prescriptions" element={<PrescriptionsModulePage />} />
            {/* UI-3: workflows (appointments, admissions, tasks) */}
            <Route path="workflows" element={<WorkflowsLayout />}>
              <Route index element={<WorkflowsIndex />} />
              <Route path="appointments" element={<AppointmentsPanel />} />
              <Route path="appointments/new" element={<BookAppointmentPage />} />
              <Route path="admissions" element={<AdmissionsPanel />} />
              <Route path="admissions/new" element={<RequestAdmissionPage />} />
              <Route path="tasks" element={<TasksPanel />} />
              <Route path="tasks/new" element={<AreaGuard permission="workflow.manage"><NewTaskPage /></AreaGuard>} />
            </Route>
            {/* UI-4: account, administration (each page also guards its own permission) */}
            <Route path="account" element={<AccountPage />} />
            <Route path="ai" element={<AiModulePage />} />
            <Route path="staff" element={<StaffPage />} />
            <Route path="administration" element={<AdminLayout />}>
              <Route index element={<AdminIndex />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="users/:userId" element={<UserDetailPage />} />
              <Route path="roles" element={<RolesPage />} />
              <Route path="roles/:roleId" element={<RoleDetailPage />} />
              <Route path="permissions" element={<PermissionsPage />} />
              <Route path="audit" element={<AuditPage />} />
            </Route>
            {ALL_NAV_ITEMS.filter((item) => item.planned).map((item) => (
              <Route key={item.id} path={item.to.slice(1)} element={<ModulePage item={item} />} />
            ))}
            {import.meta.env.DEV ? <Route path="design-system" element={<DesignSystemPage />} /> : null}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
