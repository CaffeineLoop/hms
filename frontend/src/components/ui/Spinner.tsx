import './Spinner.css'

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" style={{ width: size, height: size }} role={label ? 'status' : undefined}
      aria-label={label} aria-hidden={label ? undefined : true} />
  )
}

/** Placeholder block shown while content loads (keeps layout stable, avoids jumpy screens). */
export function Skeleton({ width = '100%', height = 12, radius = 4 }: { width?: number | string; height?: number; radius?: number }) {
  return <span className="skeleton" style={{ width, height, borderRadius: radius }} aria-hidden="true" />
}
