import { useRef, useState, type InputHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { FIELD_CLASS } from './fieldStyles'
import { FormField } from './FormField'
import { Calendar } from './icons'

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> {
  label: string
  /** YYYY-MM-DD (или YYYY-MM-DDTHH:mm с withTime) либо пусто. */
  value: string
  onChange: (value: string) => void
  error?: string
  hint?: string
  hideLabel?: boolean
  withTime?: boolean
  fieldClassName?: string
}

const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/
const HUMAN = /^(\d{2})\.(\d{2})\.(\d{4})(?: (\d{2}):(\d{2}))?$/

/** ISO -> «дд.мм.гггг» или «дд.мм.гггг чч:мм» (не зависит от языка браузера). */
export function formatDate(iso: string, withTime: boolean): string {
  const m = ISO.exec(iso)
  if (!m) return ''
  const date = `${m[3] ?? ''}.${m[2] ?? ''}.${m[1] ?? ''}`
  return withTime ? `${date} ${m[4] ?? '00'}:${m[5] ?? '00'}` : date
}

function valid(y: number, mo: number, d: number): boolean {
  const dt = new Date(Date.UTC(y, mo - 1, d))
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d
}

/** Разбор текста поля: «дд.мм.гггг [чч:мм]» либо ISO (вставка, тесты) -> ISO; null - пока неполно или неверно. */
export function parseDate(text: string, withTime: boolean): string | null {
  const iso = ISO.exec(text)
  const h = HUMAN.exec(text)
  const parts = iso
    ? { y: Number(iso[1]), mo: Number(iso[2]), d: Number(iso[3]), hh: iso[4], mm: iso[5] }
    : h
      ? { y: Number(h[3]), mo: Number(h[2]), d: Number(h[1]), hh: h[4], mm: h[5] }
      : null
  if (!parts || !valid(parts.y, parts.mo, parts.d)) return null
  const date = `${String(parts.y).padStart(4, '0')}-${String(parts.mo).padStart(2, '0')}-${String(parts.d).padStart(2, '0')}`
  if (!withTime) return date
  const hh = Number(parts.hh ?? '0')
  const mm = Number(parts.mm ?? '0')
  if (hh > 23 || mm > 59) return null
  return `${date}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/** Маска ввода цифр: 27112026 -> 27.11.2026, с временем: 271120260930 -> 27.11.2026 09:30. */
function mask(raw: string, withTime: boolean): string {
  const d = raw.replace(/\D/g, '').slice(0, withTime ? 12 : 8)
  let out = d.slice(0, 2)
  if (d.length > 2) out += `.${d.slice(2, 4)}`
  if (d.length > 4) out += `.${d.slice(4, 8)}`
  if (withTime && d.length > 8) out += ` ${d.slice(8, 10)}`
  if (withTime && d.length > 10) out += `:${d.slice(10, 12)}`
  return out
}

/**
 * Поле даты (или даты со временем): показывает «дд.мм.гггг» независимо от языка браузера, ввод с маской,
 * календарь открывается кнопкой справа. Значение наружу - строка YYYY-MM-DD / YYYY-MM-DDTHH:mm.
 */
export function DateInput({ value, onChange, withTime = false, label, error, hint, hideLabel, required, fieldClassName, className = '', ...rest }: Props) {
  const { t } = useTranslation()
  // draft - текст, пока пользователь печатает; иначе показываем отформатированное значение
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? formatDate(value, withTime)
  const picker = useRef<HTMLInputElement>(null)
  const change = (raw: string) => {
    const typedIso = raw.includes('-') || raw.includes('T')
    const next = typedIso ? raw : mask(raw, withTime)
    setDraft(next)
    if (next === '') { onChange(''); return }
    const parsed = parseDate(next, withTime)
    if (parsed !== null) onChange(parsed)
  }
  return (
    <FormField label={label} error={error} hint={hint} hideLabel={hideLabel} required={required} className={fieldClassName}>
      {(aria) => (
        <span className="relative block">
          <input
            {...aria}
            {...rest}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder={withTime ? t('common.dateTimePlaceholder') : t('common.datePlaceholder')}
            value={text}
            onChange={(event) => { change(event.target.value) }}
            onBlur={() => { setDraft(null) }}
            className={`${FIELD_CLASS} pr-10 ${className}`}
          />
          <button
            type="button"
            tabIndex={-1}
            disabled={rest.disabled}
            aria-label={t('common.openCalendar')}
            title={t('common.openCalendar')}
            onClick={() => {
              const el = picker.current
              if (!el) return
              if (typeof el.showPicker === 'function') { try { el.showPicker(); return } catch { /* не поддерживается */ } }
              el.focus()
            }}
            className="absolute right-1 top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-50"
          >
            <Calendar className="size-4" aria-hidden="true" />
          </button>
          {/* родной выбор даты: скрыт, служит только календарём */}
          <input
            ref={picker}
            type={withTime ? 'datetime-local' : 'date'}
            tabIndex={-1}
            aria-hidden="true"
            value={value}
            onChange={(event) => { setDraft(null); onChange(event.target.value) }}
            className="pointer-events-none absolute bottom-0 right-0 size-0 opacity-0"
          />
        </span>
      )}
    </FormField>
  )
}
