/**
 * Authentication state for the UI, backed by the existing Stage 5/6 endpoints:
 *   POST /api/auth/login -> opaque bearer token + the user's effective permissions
 *   GET  /api/auth/me    -> validates a restored session
 *   POST /api/auth/logout
 *
 * The token lives in sessionStorage (cleared when the tab/browser session ends); the backend remains the
 * authority on idle timeout and revocation — any 401 returns the user to sign-in.
 * `can()` only decides what to SHOW; every action is still authorized by the backend.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { configureApiClient } from '../api/client'
import { authApi } from '../api/endpoints'
import type { Me } from '../api/types'
import { AuthContext } from './context'
import type { AuthState } from './context'

const STORAGE_KEY = 'hms.session'
const SESSION_ENDED = 'Your session has ended. Please sign in again.'


function readToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(STORAGE_KEY, token)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readToken())
  const [user, setUser] = useState<Me | null>(null)
  const [status, setStatus] = useState<AuthState['status']>(() => (readToken() ? 'restoring' : 'signed-out'))
  const [sessionEndedReason, setSessionEndedReason] = useState<string | null>(null)

  const clear = useCallback((reason: string | null) => {
    writeToken(null)
    setToken(null)
    setUser(null)
    setStatus('signed-out')
    setSessionEndedReason(reason)
  }, [])

  useEffect(() => {
    configureApiClient({
      token: () => readToken(),
      onUnauthorized: () => clear(SESSION_ENDED),
    })
  }, [clear])

  useEffect(() => {
    if (!token || user) return
    const controller = new AbortController()
    authApi
      .me(controller.signal)
      .then((me) => {
        setUser(me)
        setStatus('signed-in')
      })
      .catch((error: Error & { status?: number }) => {
        // A stored session the backend no longer accepts (idle timeout, revoked, signed out elsewhere) is explained.
        if (error.name !== 'AbortError') clear(error.status === 401 ? SESSION_ENDED : null)
      })
    return () => controller.abort()
  }, [token, user, clear])

  const login = useCallback(async (username: string, password: string) => {
    const response = await authApi.login(username, password)
    writeToken(response.access_token)
    setToken(response.access_token)
    setUser(response.user)
    setStatus('signed-in')
    setSessionEndedReason(null)
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      /* the session may already be revoked; sign out locally regardless */
    }
    clear(null)
  }, [clear])

  const logoutAll = useCallback(async () => {
    await authApi.logoutAll() // errors propagate: the caller shows them and the user stays signed in
    clear('You have been signed out of all your sessions on every device.')
  }, [clear])

  const value = useMemo<AuthState>(() => {
    const codes = new Set(user?.permissions.map((p) => p.code) ?? [])
    const can = (permission: string) => Boolean(user && (user.is_superuser || codes.has(permission)))
    const scopes = new Map(user?.permissions.map((p) => [p.code, p.scope]) ?? [])
    const canReadClinical = (permission: string) => Boolean(user && (user.is_superuser
      || (scopes.get(permission) === 'ALL' && scopes.get('patient.view') === 'ALL')))
    return {
      status,
      user,
      sessionEndedReason,
      login,
      logout,
      logoutAll,
      can,
      canAny: (...permissions: string[]) => permissions.some(can),
      canReadClinical,
      hasAllScope: (permission: string) => Boolean(user && (user.is_superuser || scopes.get(permission) === 'ALL')),
    }
  }, [status, user, sessionEndedReason, login, logout, logoutAll])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
