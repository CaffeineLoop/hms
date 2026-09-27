import { useContext } from 'react'
import { AuthContext } from './context'
import type { AuthState } from './context'

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
