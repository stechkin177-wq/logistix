import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { FIELD_CLASS } from './fieldStyles'
import { FormField } from './FormField'
import { Search } from './icons'

type Common = { label: string; error?: string; hint?: string; hideLabel?: boolean; fieldClassName?: string }

export function TextField({
  label, error, hint, hideLabel, fieldClassName, required, className = '', ...rest
}: Common & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => {
        if (rest.type !== 'search') return <input {...aria} {...rest} className={`${FIELD_CLASS} ${className}`} />
        // поле поиска: значок лупы слева, ширина по тексту подсказки
        // ширина по тексту: подсказка или введённое значение (что длиннее), с запасом под лупу и поля
        const typed = typeof rest.value === 'string' ? rest.value.length : 0
        const chars = Math.max((rest.placeholder ?? '').length, typed)
        const width = `min(100%, max(8rem, calc(${String(chars)}ch * 0.98 + 4.25rem)))`
        return (
          <span className="relative block text-sm max-sm:w-full!" style={{ width }}>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input {...aria} {...rest} className={`${FIELD_CLASS} pl-9 ${className}`} />
          </span>
        )
      }}
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
