import type { InputHTMLAttributes, ReactNode } from 'react'

/** Флажок с подписью; зона нажатия не меньше 32 px по высоте. */
export function Checkbox({
  label, hideLabel, className = '', ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode; hideLabel?: boolean }) {
  return (
    <label className={`inline-flex min-h-8 items-center gap-1.5 text-sm ${className}`}>
      <input type="checkbox" className="size-4 rounded accent-brand-600" {...rest} />
      <span className={hideLabel ? 'sr-only' : ''}>{label}</span>
    </label>
  )
}
