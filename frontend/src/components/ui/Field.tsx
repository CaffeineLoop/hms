import { cloneElement, forwardRef, isValidElement, useId } from 'react'
import type { InputHTMLAttributes, ReactElement, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { Icon } from '../icons/Icon'
import type { IconName } from '../icons/Icon'
import './Field.css'

interface FieldProps {
  label: string
  hint?: string
  error?: string | null
  required?: boolean
  children: ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean; required?: boolean }>
}

/** Label + control + hint/error, wired with ids so screen readers announce them together. */
export function Field({ label, hint, error, required, children }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  const control = isValidElement(children)
    ? cloneElement(children, { id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined, required })
    : children
  return (
    <div className={['field', error ? 'field--invalid' : ''].join(' ')}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? <span className="field__required" aria-hidden="true">*</span> : null}
      </label>
      {control}
      {hint && !error ? <p className="field__hint" id={hintId}>{hint}</p> : null}
      {error ? (
        <p className="field__error" id={errorId} role="alert">
          <Icon name="alert" size={14} /> {error}
        </p>
      ) : null}
    </div>
  )
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: IconName
  suffix?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ icon, suffix, className, ...rest }, ref) {
  if (!icon && !suffix) return <input ref={ref} className={['input', className ?? ''].join(' ')} {...rest} />
  return (
    <span className={['input-group', icon ? 'input-group--icon' : '', suffix ? 'input-group--suffix' : '', className ?? ''].join(' ')}>
      {icon ? <Icon name={icon} size={16} className="input-group__icon" /> : null}
      <input ref={ref} className="input" {...rest} />
      {suffix ? <span className="input-group__suffix">{suffix}</span> : null}
    </span>
  )
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest }, ref,
) {
  return (
    <span className="select">
      <select ref={ref} className={['input', 'select__control', className ?? ''].join(' ')} {...rest}>{children}</select>
      <Icon name="chevronDown" size={16} className="select__chevron" />
    </span>
  )
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, rows = 4, ...rest }, ref,
) {
  return <textarea ref={ref} rows={rows} className={['input', 'textarea', className ?? ''].join(' ')} {...rest} />
})
