import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { FIELD_CLASS } from './fieldStyles'
import { FormField } from './FormField'

type Common = { label: string; error?: string; hint?: string; hideLabel?: boolean; fieldClassName?: string }

export function TextField({
  label, error, hint, hideLabel, fieldClassName, required, className = '', ...rest
}: Common & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => <input {...aria} {...rest} className={`${FIELD_CLASS} ${className}`} />}
    </FormField>
  )
}

export function TextArea({
  label, error, hint, hideLabel, fieldClassName, required, className = '', ...rest
}: Common & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => (
        <textarea {...aria} {...rest} className={`${FIELD_CLASS} h-auto min-h-16 py-1 ${className}`} />
      )}
    </FormField>
  )
}
