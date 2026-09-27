import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import { Spinner } from './Spinner'
import './Button.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface CommonProps {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: IconName
  iconRight?: IconName
  block?: boolean
  children?: ReactNode
}

export interface ButtonProps extends CommonProps, Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  loading?: boolean
}

function classes({ variant = 'secondary', size = 'md', block }: CommonProps, extra?: string) {
  return ['btn', `btn--${variant}`, `btn--${size}`, block ? 'btn--block' : '', extra ?? ''].filter(Boolean).join(' ')
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, icon, iconRight, block, loading = false, disabled, children, className, type = 'button', ...rest },
  ref,
) {
  const iconSize = size === 'sm' ? 15 : 16
  return (
    <button
      ref={ref}
      type={type}
      className={classes({ variant, size, block }, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={iconSize} /> : icon ? <Icon name={icon} size={iconSize} /> : null}
      {children ? <span className="btn__label">{children}</span> : null}
      {iconRight && !loading ? <Icon name={iconRight} size={iconSize} /> : null}
    </button>
  )
})

/** A navigation link that looks like a button (keeps link semantics for routing). */
export function LinkButton({ to, variant, size, icon, iconRight, block, children }: CommonProps & { to: string }) {
  const iconSize = size === 'sm' ? 15 : 16
  return (
    <Link to={to} className={classes({ variant, size, block })}>
      {icon ? <Icon name={icon} size={iconSize} /> : null}
      {children ? <span className="btn__label">{children}</span> : null}
      {iconRight ? <Icon name={iconRight} size={iconSize} /> : null}
    </Link>
  )
}

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName
  label: string
  variant?: 'ghost' | 'secondary'
  size?: ButtonSize
  badge?: number
}

/** Icon-only button. `label` is mandatory: it becomes the accessible name and the tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, variant = 'ghost', size = 'md', badge, className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={['icon-btn', `icon-btn--${variant}`, `icon-btn--${size}`, className ?? ''].join(' ')}
      {...rest}
    >
      <Icon name={icon} size={size === 'sm' ? 16 : 18} />
      {badge ? <span className="icon-btn__badge tabular" aria-hidden="true">{badge > 99 ? '99+' : badge}</span> : null}
    </button>
  )
})
