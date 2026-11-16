import { useLayoutEffect, useRef, useState, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { FIELD_CLASS } from './fieldStyles'
import { FormField } from './FormField'
import { Search } from './icons'

type Common = { label: string; error?: string; hint?: string; hideLabel?: boolean; fieldClassName?: string }

/** Поле поиска: лупа слева, ширина точно по тексту (подсказка или введённое значение), измеряется шрифтом самого поля. */
function SearchInput({ aria, rest, className }: { aria: object; rest: InputHTMLAttributes<HTMLInputElement>; className: string }) {
  const ref = useRef<HTMLInputElement>(null)
  const [px, setPx] = useState<number | null>(null)
  const text = (typeof rest.value === 'string' && rest.value.length > (rest.placeholder ?? '').length ? rest.value : rest.placeholder) ?? ''
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const ctx = document.createElement('canvas').getContext('2d')
      if (!ctx) return
      const cs = getComputedStyle(el)
      // собираем шрифт вручную: сокращённое свойство font в части браузеров приходит пустым
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
      // слева лупа и отступ (36), справа отступ (12) и место под крестик очистки (20), плюс запас на округление
      setPx(Math.ceil(ctx.measureText(text).width) + 36 + 12 + 20 + 6)
    }
    measure()
    // после загрузки шрифтов ширина букв меняется - измеряем заново
    const fonts = (document as { fonts?: { ready: Promise<unknown> } }).fonts
    if (fonts) void fonts.ready.then(measure)
  }, [text])
  return (
    <span className="relative block max-sm:w-full!" style={{ width: px === null ? '12rem' : `${String(Math.max(px, 128))}px`, maxWidth: '100%' }}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
      <input {...aria} {...rest} ref={ref} className={`${FIELD_CLASS} pl-9 ${className}`} />
    </span>
  )
}

export function TextField({
  label, error, hint, hideLabel, fieldClassName, required, className = '', ...rest
}: Common & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => {
        if (rest.type !== 'search') return <input {...aria} {...rest} className={`${FIELD_CLASS} ${className}`} />
        return <SearchInput aria={aria} rest={rest} className={className} />
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
