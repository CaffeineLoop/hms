import { initials } from '../../lib/format'
import './Avatar.css'

export function Avatar({ name, size = 32, tone = 'primary' }: { name: string; size?: number; tone?: 'primary' | 'neutral' }) {
  return (
    <span className={`avatar avatar--${tone}`} style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
      aria-hidden="true">
      {initials(name)}
    </span>
  )
}
