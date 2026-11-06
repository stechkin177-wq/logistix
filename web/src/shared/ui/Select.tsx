import type { SelectHTMLAttributes } from 'react'
import { FIELD_CLASS } from './fieldStyles'
import { FormField } from './FormField'

export interface Option {
  value: string
  label: string
}

interface Props extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'value' | 'onChange'> {
  label: string
  options: Option[]
  value: string
  onChange: (value: string) => void
  /** Пункт «не выбрано» (пустое значение); без него пустого пункта нет. */
  placeholder?: string
  error?: string
  hint?: string
  hideLabel?: boolean
  fieldClassName?: string
}

export function Select({
  label, options, value, onChange, placeholder, error, hint, hideLabel, fieldClassName, required, className = '', ...rest
}: Props) {
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => (
        <select
          {...aria}
          {...rest}
          value={value}
          onChange={(event) => {
            onChange(event.target.value)
          }}
          className={`${FIELD_CLASS} ${className}`}
        >
          {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </FormField>
  )
}
