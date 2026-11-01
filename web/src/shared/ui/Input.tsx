import { useId, type InputHTMLAttributes } from 'react'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
}

export function Input({ label, error, className = '', id, ...rest }: InputProps) {
  const generated = useId()
  const inputId = id ?? generated
  const errorId = `${inputId}-error`
  return (
    <div className="space-y-1">
      <label htmlFor={inputId} className="block text-xs font-medium text-slate-600 dark:text-slate-300">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={`h-8 w-full rounded border border-slate-300 bg-white px-2 text-sm text-slate-900 outline-brand-500 focus:outline-2 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 ${className}`}
        {...rest}
      />
      {error ? (
        <p id={errorId} className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  )
}
