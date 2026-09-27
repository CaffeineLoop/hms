/**
 * Thin fetch wrapper for the existing FastAPI backend (same-origin via the dev/preview proxy).
 * - attaches the bearer token;
 * - maps HMS error responses ({"detail": ...}) to ApiError with the HTTP status;
 * - notifies the auth layer on 401 so an expired/revoked session returns to sign-in.
 */

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  get isForbidden() { return this.status === 403 }
  get isUnauthorized() { return this.status === 401 }
}

type TokenProvider = () => string | null
type UnauthorizedHandler = () => void

let tokenProvider: TokenProvider = () => null
let onUnauthorized: UnauthorizedHandler = () => {}

export function configureApiClient(options: { token: TokenProvider; onUnauthorized: UnauthorizedHandler }) {
  tokenProvider = options.token
  onUnauthorized = options.onUnauthorized
}

function messageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] }
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== 'body').join('.') : ''
    return field ? `${field}: ${first.msg ?? 'invalid value'}` : first.msg ?? 'Invalid request.'
  }
  if (status === 403) return 'You do not have permission to perform this action.'
  if (status === 404) return 'The requested record was not found.'
  if (status === 429) return 'Too many attempts. Please wait and try again.'
  if (status >= 500) return 'The HMS service is temporarily unavailable.'
  return `Request failed (${status}).`
}

export type QueryValue = string | number | boolean | null | undefined
/** Array values are sent as repeated parameters (e.g. ?types=a&types=b). */
export type Query = Record<string, QueryValue | readonly string[]>

function buildUrl(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item))
    else if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

export async function apiRequest<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE',
  path: string,
  options: { query?: Query; body?: unknown; signal?: AbortSignal; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = options.auth === false ? null : tokenProvider()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError(0, 'Cannot reach the HMS service. Check your connection.', null)
  }

  if (response.status === 204) return undefined as T
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && token) onUnauthorized()
    throw new ApiError(response.status, messageFrom(response.status, body), body)
  }
  return body as T
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => apiRequest<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>('POST', path, { body }),
  patch: <T>(path: string, body: unknown) => apiRequest<T>('PATCH', path, { body }),
}

/** Field-level messages from a FastAPI 422 response: { field_name: message }. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  const detail = (error.detail as { detail?: unknown } | null)?.detail
  if (!Array.isArray(detail)) return {}
  const result: Record<string, string> = {}
  for (const item of detail as Array<{ loc?: unknown[]; msg?: string }>) {
    const field = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : ''
    if (field && item.msg && !result[field]) result[field] = item.msg.replace(/^Value error, /, '')
  }
  return result
}
