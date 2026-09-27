/**
 * Minimal data-loading hook: data / error / loading with abort on change or unmount, and manual reload.
 * `loading` is derived (the latest request has not settled yet); state is only set from async results.
 * Previous data is kept while a reload is in flight, so screens do not flash empty.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface QueryState<T> {
  data: T | undefined
  error: ApiError | null
  loading: boolean
  reload: () => void
}

interface Settled<T> {
  key: string
  data: T | undefined
  error: ApiError | null
}

export function useQuery<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean } = {},
): QueryState<T> {
  const enabled = options.enabled ?? true
  const [version, setVersion] = useState(0)
  const key = `${JSON.stringify(deps)}#${version}`
  const [settled, setSettled] = useState<Settled<T>>({ key: '', data: undefined, error: null })
  const loadRef = useRef(load)
  useLayoutEffect(() => { loadRef.current = load })

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    loadRef.current(controller.signal)
      .then((data) => setSettled({ key, data, error: null }))
      .catch((err: unknown) => {
        if ((err as Error).name === 'AbortError') return
        const error = err instanceof ApiError ? err : new ApiError(0, 'Unexpected error while loading data.', err)
        setSettled((previous) => ({ key, data: previous.data, error }))
      })
    return () => controller.abort()
  }, [enabled, key])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return {
    data: settled.data,
    error: settled.key === key ? settled.error : null,
    loading: enabled && settled.key !== key,
    reload,
  }
}
