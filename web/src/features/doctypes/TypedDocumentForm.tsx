import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { serverErrors } from '../../shared/forms/serverErrors'
import { DateInput } from '../../shared/ui/DateInput'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useDocumentTypes } from './hooks'
import type { DocSubject, DocumentType } from './types'

interface Props {
  subject: DocSubject
  /** Поле даты выдачи в записи: у водителей issued_at, у техники starts_at. */
  issuedKey: 'issued_at' | 'starts_at'
  /** Право на добавление (drivers.update / fleet.create). */
  permission: string
  /** Поля владельца записи: { driver } или { vehicle }. */
  owner: Record<string, number>
  create: { mutate: (body: Record<string, unknown>, o: { onSuccess: () => void; onError: (e: unknown) => void }) => void; isPending: boolean }
  addLabel: string
}

type Values = Record<string, string>

/** Форма добавления документа: набор полей определяется типом документа, который настроила компания. */
export function TypedDocumentForm({ subject, issuedKey, permission, owner, create, addLabel }: Props) {
  const { t } = useTranslation()
  const types = useDocumentTypes(subject)
  const options = (types.data ?? []).filter((x) => x.is_active)
  const [typeId, setTypeId] = useState('')
  const [values, setValues] = useState<Values>({})
  const [extra, setExtra] = useState<Values>({})
  const [error, setError] = useState<string>()
  const type: DocumentType | undefined = options.find((x) => String(x.id) === (typeId || String(options[0]?.id ?? '')))

  if (types.isSuccess && options.length === 0) return <p className="text-sm text-muted">{t('doctypes.noTypes')}</p>
  if (!type) return null

  const label = (f: string) => t(`doctypes.fields.${f}`)
  const set = (key: string, v: string) => { setValues((s) => ({ ...s, [key]: v })) }
  const text = (key: 'number' | 'issued_by' | 'comment') => (
    <TextField key={key} label={label(key)} required={type.required.includes(key)} value={values[key] ?? ''} onChange={(e) => { set(key, e.target.value) }} />
  )
  const date = (key: 'issued_at' | 'expires_at') => (
    <DateInput key={key} label={label(key)} required={type.required.includes(key)} value={values[key] ?? ''} onChange={(v) => { set(key, v) }} />
  )

  const submit = () => {
    setError(undefined)
    const missing = [
      ...type.required.filter((f) => !values[f]).map(label),
      ...type.extra.filter((f) => f.required && !extra[f.key]).map((f) => f.label),
    ]
    if (missing.length > 0) { setError(`${missing.join(', ')}: ${t('errors.requiredField')}`); return }
    const body: Record<string, unknown> = { ...owner, doc_type: type.id }
    for (const f of type.fields) {
      const v = values[f]
      if (!v) continue
      body[f === 'issued_at' ? issuedKey : f === 'comment' ? 'notes' : f] = v
    }
    const extraBody = Object.fromEntries(type.extra.filter((f) => extra[f.key]).map((f) => [f.key, extra[f.key]]))
    if (Object.keys(extraBody).length > 0) body.extra = extraBody
    create.mutate(body, {
      onSuccess: () => { setValues({}); setExtra({}) },
      onError: (e) => {
        const err = serverErrors(e, t)
        setError(err.banner ?? Object.values(err.fields).join(' '))
      },
    })
  }

  return (
    <div className="grid grid-cols-2 gap-2">
      <Select
        label={t('doctypes.type')}
        value={String(type.id)}
        options={options.map((x) => ({ value: String(x.id), label: x.name }))}
        onChange={(v) => { setTypeId(v); setValues({}); setExtra({}) }}
      />
      {type.fields.includes('number') ? text('number') : null}
      {type.fields.includes('issued_by') ? text('issued_by') : null}
      {type.fields.includes('issued_at') ? date('issued_at') : null}
      {type.fields.includes('expires_at') ? date('expires_at') : null}
      {type.extra.map((f) => (
        <TextField key={f.key} label={f.label} required={f.required} value={extra[f.key] ?? ''} onChange={(e) => { setExtra((s) => ({ ...s, [f.key]: e.target.value })) }} />
      ))}
      {type.fields.includes('comment') ? text('comment') : null}
      <div className="col-span-2">
        <WriteButton permission={permission} onClick={submit} disabled={create.isPending}>{addLabel}</WriteButton>
      </div>
      {error ? <p role="alert" className="col-span-2 text-sm text-red-600">{error}</p> : null}
    </div>
  )
}

/** Строка списка: тип (название у записи, а для старых - прежний вид), номер, срок. */
export function documentSummary(d: { doc_type_name?: string; number?: string; expires_at?: string | null }, legacy: string, until: string): string {
  return `${d.doc_type_name || legacy} ${d.number ?? ''}${d.expires_at ? ` · ${until} ${d.expires_at}` : ''}`.replace(/\s+/g, ' ').trim()
}
