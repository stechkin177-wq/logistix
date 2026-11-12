import { useId, type ReactNode } from 'react'

export interface FieldAria {
  id: string
  'aria-invalid'?: true
  'aria-describedby'?: string
  'aria-required'?: true
}

interface Props {
  label: string
  error?: string
  hint?: string
  required?: boolean
  /** Подпись только для скринридера (фильтры в строке). */
  hideLabel?: boolean
  className?: string
  children: (aria: FieldAria) => ReactNode
}

/** Подпись + поле + ошибка. Поле получает id, aria-invalid и aria-describedby. */
export function FormField({ label, error, hint, required, hideLabel, className = '', children }: Props) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')
  return (
    <div className={`space-y-1 ${className}`}>
      <label
        htmlFor={id}
        className={hideLabel ? 'sr-only' : 'block text-xs font-medium text-muted'}
      >
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {children({
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy || undefined,
        'aria-required': required ? true : undefined,
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  )
}
