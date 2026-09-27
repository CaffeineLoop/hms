/** Auth context object and its type (kept separate from components for fast refresh). */
import { createContext } from 'react'
import type { Me } from '../api/types'

export interface AuthState {
  status: 'restoring' | 'signed-out' | 'signed-in'
  user: Me | null
  sessionEndedReason: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Revokes all of this user's sessions (backend), then signs out here. */
  logoutAll: () => Promise<void>
  can: (permission: string) => boolean
  canAny: (...permissions: string[]) => boolean
  /** Mirrors the backend clinical-read rule: `permission` and patient.view both at ALL scope (OWN grants no access). */
  canReadClinical: (permission: string) => boolean
  /** True when `permission` is held at ALL scope (e.g. workflow.manage: ALL may create/assign; OWN only own tasks). */
  hasAllScope: (permission: string) => boolean
}

export const AuthContext = createContext<AuthState | null>(null)
