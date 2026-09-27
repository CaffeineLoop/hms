/** Presentation helpers. The backend stores and returns UTC; the UI shows local time explicitly. */

const dateFormat = new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})
const longDate = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

export const formatDate = (iso: string) => dateFormat.format(new Date(iso))
export const formatTime = (iso: string) => timeFormat.format(new Date(iso))
export const formatDateTime = (iso: string) => dateTimeFormat.format(new Date(iso))
export const formatLongDate = (date: Date) => longDate.format(date)

/** Compact date-time for dense tables: "Today, 14:52", "Tomorrow, 09:10", "27 Sep, 14:52". */
export function formatShortDateTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const dayDiff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() -
    new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86_400_000)
  const time = timeFormat.format(d)
  if (dayDiff === 0) return `Today, ${time}`
  if (dayDiff === 1) return `Tomorrow, ${time}`
  if (dayDiff === -1) return `Yesterday, ${time}`
  return `${new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(d)}, ${time}`
}

export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000)
  const abs = Math.abs(seconds)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (abs < 60) return rtf.format(seconds, 'second')
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86400 * 7) return rtf.format(Math.round(seconds / 86400), 'day')
  return formatDate(iso)
}

/** Age in completed years from an ISO date of birth. */
export function ageFromDob(dob: string, now: Date = new Date()): number {
  const birth = new Date(`${dob}T00:00:00`)
  let age = now.getFullYear() - birth.getFullYear()
  const beforeBirthday = now.getMonth() < birth.getMonth() ||
    (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())
  if (beforeBirthday) age -= 1
  return age
}

/** Clinical convention: FAMILY name first, in capitals, then given names. */
export function patientDisplayName(p: { first_name: string; middle_name?: string | null; last_name: string }): string {
  return `${p.last_name.toUpperCase()}, ${[p.first_name, p.middle_name].filter(Boolean).join(' ')}`
}

export function initials(name: string): string {
  const parts = name.replace(/[^\p{L}\s-]/gu, ' ').split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?'
}

export function humanize(code: string): string {
  const text = code.replace(/[_.]/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function greeting(now: Date = new Date()): string {
  const hour = now.getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

export function sexLabel(sex: string): string {
  return { MALE: 'Male', FEMALE: 'Female', OTHER: 'Other', UNKNOWN: 'Unknown' }[sex] ?? sex
}
