/**
 * Navigation registry. Later UI stages enable a module by giving it a real page — the shell never changes.
 * `anyOf` lists the HMS permission codes that make a module relevant to a user; items the user cannot use are
 * hidden (the backend still enforces every permission).
 */
import type { IconName } from '../icons/Icon'

export interface NavItem {
  id: string
  label: string
  to: string
  icon: IconName
  anyOf: string[]
  summary: string
  /** Not yet implemented in the UI: shown as a planned module. */
  planned?: string
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAVIGATION: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard', label: 'Dashboard', to: '/', icon: 'dashboard', anyOf: [], summary: 'Your day at a glance.' },
    ],
  },
  {
    label: 'Clinical care',
    items: [
      { id: 'patients', label: 'Patients', to: '/patients', icon: 'patients', anyOf: ['patient.view'],
        summary: 'Register, search and identify patients.' },
      { id: 'clinical', label: 'Clinical records', to: '/clinical', icon: 'clinical',
        anyOf: ['encounter.view', 'observation.view', 'condition.view', 'allergy.view', 'clinical_note.view', 'timeline.view'],
        summary: 'Encounters, vitals, conditions, allergies, notes and the patient timeline.' },
      { id: 'diagnostics', label: 'Diagnostics', to: '/diagnostics', icon: 'diagnostics', anyOf: ['lab.view', 'report.view'],
        summary: 'Laboratory orders, results and clinical reports.' },
      { id: 'prescriptions', label: 'Prescriptions', to: '/prescriptions', icon: 'prescriptions', anyOf: ['prescription.view'],
        summary: 'Prescribing lifecycle and medication review.' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { id: 'workflows', label: 'Workflows', to: '/workflows', icon: 'workflows',
        anyOf: ['workflow.view', 'appointment.view', 'admission.view'],
        summary: 'Appointments, admissions and ward tasks.' },
      { id: 'staff', label: 'Staff', to: '/staff', icon: 'staff', anyOf: ['staff.view'],
        summary: 'Departments and staff directory.' },
    ],
  },
  {
    label: 'Clinical decision support',
    items: [
      { id: 'ai', label: 'AI analysis', to: '/ai', icon: 'ai', anyOf: ['ai.analysis', 'ai.review'],
        summary: 'Read-only, evidence-grounded analysis and four-day potential risk signals for clinician review.' },
    ],
  },
  {
    label: 'System',
    items: [
      { id: 'administration', label: 'Administration', to: '/administration', icon: 'administration',
        anyOf: ['user.view', 'user.manage', 'role.manage', 'permission.manage', 'audit.view'],
        summary: 'Users, roles, permissions and the audit trail.' },
    ],
  },
]

export const ALL_NAV_ITEMS = NAVIGATION.flatMap((group) => group.items)
