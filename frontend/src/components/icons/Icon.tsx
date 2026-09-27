/**
 * Minimal in-house stroke icon set (24x24, 1.6px stroke) — keeps the UI dependency-free and visually consistent.
 * Icons are decorative by default (aria-hidden); pass `label` when an icon carries meaning on its own.
 */
const PATHS = {
  dashboard: 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z',
  patients: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20M10 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35M15.5 4.65a3.5 3.5 0 0 1 0 6.7',
  clinical: 'M9 4h6v3H9zM9 5.5H6.5A1.5 1.5 0 0 0 5 7v12.5A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V7a1.5 1.5 0 0 0-1.5-1.5H15M12 11v6M9 14h6',
  diagnostics: 'M9 3h6M10 3v6.2L5.2 17.4A2.4 2.4 0 0 0 7.3 21h9.4a2.4 2.4 0 0 0 2.1-3.6L14 9.2V3M7.5 14h9',
  prescriptions: 'M10.5 20.5 3.5 13.5a4.95 4.95 0 0 1 7-7l7 7a4.95 4.95 0 0 1-7 7ZM8.5 8.5l7 7',
  workflows: 'M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2',
  staff: 'M4 7.5A1.5 1.5 0 0 1 5.5 6h13A1.5 1.5 0 0 1 20 7.5v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5zM9 3h6v3H9zM10 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4M7 16.5c.6-1.5 1.7-2.3 3-2.3s2.4.8 3 2.3M15.5 11h2M15.5 14h2',
  administration: 'M12 3l7.5 3v5.5c0 4.5-3.1 8.3-7.5 9.5-4.4-1.2-7.5-5-7.5-9.5V6zM9.5 12l1.8 1.8 3.5-3.6',
  ai: 'M5 4.5h9l5 5v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1zM8 13.5h3M8 16.5h5M15 18.5l1.6-1.6M13.3 15.3a2 2 0 1 0 2.8 2.8 2 2 0 0 0-2.8-2.8',
  bell: 'M18 9.5a6 6 0 1 0-12 0c0 6.5-2.5 8-2.5 8h17S18 16 18 9.5M10.3 20.5a2 2 0 0 0 3.4 0',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M20 20l-3.9-3.9',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 6l6 6-6 6',
  chevronLeft: 'M15 6l-6 6 6 6',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  alert: 'M12 4 2.8 19.5a1 1 0 0 0 .9 1.5h16.6a1 1 0 0 0 .9-1.5L12 4ZM12 10v4.5M12 17.5v.01',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 11v5.5M12 7.5v.01',
  checkCircle: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M8.5 12.2l2.4 2.4 4.6-4.8',
  xCircle: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7.5V12l3 2',
  calendar: 'M5 5.5h14a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1zM4 10h16M8.5 3.5v4M15.5 3.5v4',
  bed: 'M3 18V6M3 14h18v4M21 14v-2.5a3 3 0 0 0-3-3h-7v5.5M7 12a1.8 1.8 0 1 0 0-3.6A1.8 1.8 0 0 0 7 12',
  logout: 'M15 4h3.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H15M10 16l4-4-4-4M14 12H4',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M5 20.5c.9-3.3 3.6-5.3 7-5.3s6.1 2 7 5.3',
  lock: 'M6 10.5h12a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8.5a1 1 0 0 1 1-1zM8 10.5V8a4 4 0 0 1 8 0v2.5',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  filter: 'M4 5h16l-6.2 7.3V19l-3.6-1.8v-4.9z',
  more: 'M6 12h.01M12 12h.01M18 12h.01',
  refresh: 'M20 12a8 8 0 1 1-2.35-5.65M20 4v5h-5',
  collapse: 'M4 5h16v14H4zM9 5v14M15.5 10l-2 2 2 2',
  expand: 'M4 5h16v14H4zM9 5v14M13.5 10l2 2-2 2',
  pulse: 'M3 12h4l2.5-6 4 12 2.5-6h5',
  document: 'M6.5 3.5H14l4.5 4.5v12a.5.5 0 0 1-.5.5H6.5a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5zM14 3.5V8h4.5M9 13h6M9 16.5h6',
  shieldCheck: 'M12 3l7.5 3v5.5c0 4.5-3.1 8.3-7.5 9.5-4.4-1.2-7.5-5-7.5-9.5V6zM9.5 12l1.8 1.8 3.5-3.6',
  trash: 'M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.8 12.1a1 1 0 0 0 1 .9h7.4a1 1 0 0 0 1-.9L17.5 7M10 11v5.5M14 11v5.5',
  edit: 'M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4',
  inbox: 'M3.5 13.5 6 5h12l2.5 8.5V19a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1zM3.5 13.5H9l1 2h4l1-2h5.5',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
} as const

export type IconName = keyof typeof PATHS

interface IconProps {
  name: IconName
  size?: number
  label?: string
  className?: string
  strokeWidth?: number
}

export function Icon({ name, size = 18, label, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
