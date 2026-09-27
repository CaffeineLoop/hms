/** Form value helpers for UI-3 writes (formatting/structure only — clinical validation stays in the backend). */

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** Current local time for <input type="datetime-local"> ("2026-09-27T14:05"). */
export function nowLocalInput(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** A datetime-local value as a timezone-aware ISO instant (the backend requires aware timestamps); '' -> null. */
export function localInputToIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

/** A date input value ("2026-09-27") as the start of that local day, ISO; '' -> null. */
export function dateInputToIso(value: string): string | null {
  return value ? localInputToIso(`${value}T00:00`) : null
}

/** Trimmed text, or null when empty (optional backend fields). */
export function optionalText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

/** Parses a numeric input; undefined when empty, NaN when not a number. */
export function parseNumber(value: string): number | undefined {
  if (!value.trim()) return undefined
  return Number(value.replace(',', '.'))
}

/** Required-field check: { field: message } for blank values. Structural only. */
export function requireFields<T extends Record<string, string>>(form: T, labels: Partial<Record<keyof T, string>>) {
  const errors: Record<string, string> = {}
  for (const [field, label] of Object.entries(labels)) {
    if (!form[field]?.trim()) errors[field] = `Enter ${label}.`
  }
  return errors
}
