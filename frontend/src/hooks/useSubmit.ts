/**
 * Submission state for UI-3 write forms and action dialogs. The backend is the authority: its answer decides what the
 * user sees — 422 field errors on the matching fields, 409 as a state conflict, 403/404 as such, 5xx/network as a
 * failure where the outcome must be checked by reloading. Nothing is written optimistically; callers reload from the
 * API after a successful write.
 */
import { useCallback, useState } from 'react'
import { ApiError, fieldErrors } from '../api/client'

export interface FormProblem {
  tone: 'danger' | 'warning'
  title: string
  message: string
}

export function describeWriteError(error: unknown): { problem: FormProblem; fields: Record<string, string> } {
  // Model-level validation errors are reported at loc ["body"]: they belong to the form, not to one field.
  const { body: _formLevel, ...fields } = fieldErrors(error)
  if (!(error instanceof ApiError)) {
    return { fields, problem: { tone: 'danger', title: 'Could not save', message: 'An unexpected error occurred. Nothing was confirmed as saved.' } }
  }
  switch (true) {
    case error.status === 422:
      return { fields, problem: { tone: 'danger', title: Object.keys(fields).length ? 'Please correct the highlighted fields' : 'The HMS rejected these values',
        message: Object.keys(fields).length ? 'Nothing was saved.' : `${error.message.replace(/Value error, /, '')}. Nothing was saved.`.replace('..', '.') } }
    case error.status === 409:
      return { fields, problem: { tone: 'warning', title: 'Not possible in the current state', message: `${error.message} Nothing was changed.` } }
    case error.status === 403:
      return { fields, problem: { tone: 'danger', title: 'Not permitted', message: `${error.message} Nothing was changed.` } }
    case error.status === 404:
      return { fields, problem: { tone: 'danger', title: 'Record not found', message: `${error.message} Nothing was changed.` } }
    default:
      return { fields, problem: { tone: 'danger', title: 'The HMS could not complete the request',
        message: `${error.message} Reload before trying again to check whether the change was saved.` } }
  }
}

export function useSubmit() {
  const [submitting, setSubmitting] = useState(false)
  const [problem, setProblem] = useState<FormProblem | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const reset = useCallback(() => { setProblem(null); setErrors({}) }, [])

  /** Runs `write`; returns its result, or undefined when the backend rejected it (the problem is then shown). */
  const run = useCallback(async <T,>(write: () => Promise<T>): Promise<T | undefined> => {
    setSubmitting(true)
    setProblem(null)
    setErrors({})
    try {
      return await write()
    } catch (error) {
      const { problem: p, fields } = describeWriteError(error)
      setProblem(p)
      setErrors(fields)
      return undefined
    } finally {
      setSubmitting(false)
    }
  }, [])

  /** Client-side structural checks (required fields, numbers): shown like server errors, nothing is sent. */
  const reject = useCallback((fields: Record<string, string>, message = 'Nothing was saved.') => {
    setErrors(fields)
    setProblem({ tone: 'danger', title: 'Please correct the highlighted fields', message })
  }, [])

  const clearField = useCallback((field: string) => {
    setErrors((current) => {
      if (!(field in current)) return current
      const next = { ...current }
      delete next[field]
      return next
    })
  }, [])

  return { submitting, problem, errors, run, reject, reset, clearField, setProblem }
}
