import type { InputHTMLAttributes } from 'react'
import { TextField } from './TextField'

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> {
  label: string
  /** YYYY-MM-DD или пусто. */
  value: string
  onChange: (value: string) => void
  error?: string
  hideLabel?: boolean
  withTime?: boolean
}

/** Поле даты (или даты со временем, если withTime): значение - строка YYYY-MM-DD / YYYY-MM-DDTHH:mm. */
export function DateInput({ value, onChange, withTime, ...rest }: Props) {
  return (
    <TextField
      {...rest}
      type={withTime ? 'datetime-local' : 'date'}
      value={value}
      onChange={(event) => {
        onChange(event.target.value)
      }}
    />
  )
}
