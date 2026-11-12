import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Checkbox } from '../../shared/ui/Checkbox'
import { DateInput } from '../../shared/ui/DateInput'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useChildList, useCreateChild, useDeleteChild } from './hooks'

export interface FieldDef {
  key: string
  label: string
  type: 'text' | 'number' | 'date' | 'datetime' | 'select' | 'checkbox'
  options?: { value: string; label: string }[]
  required?: boolean
  initial?: string | boolean
}

interface Props {
  path: string
  vehicle: number
  fields: FieldDef[]
  /** Короткое описание строки списка. */
  summary: (row: Record<string, unknown>) => string
  emptyText: string
  /** Дополнительный блок над списком (например, средний расход). */
  header?: React.ReactNode
  /** Нет формы добавления (только чтение). */
  readOnly?: boolean
}

const initialValues = (fields: FieldDef[]) =>
  Object.fromEntries(fields.map((f) => [f.key, f.initial ?? (f.type === 'checkbox' ? false : f.type === 'select' ? f.options?.[0]?.value ?? '' : '')]))

/** Универсальная вкладка карточки техники: список записей по технике + короткая форма добавления. */
export function ChildTab({ path, vehicle, fields, summary, emptyText, header, readOnly }: Props) {
  const { t } = useTranslation()
  const list = useChildList<Record<string, unknown> & { id: number }>(path, vehicle)
  const create = useCreateChild(path)
  const remove = useDeleteChild(path)
  const [values, setValues] = useState<Record<string, string | boolean>>(() => initialValues(fields))
  const [error, setError] = useState<string>()

  const submit = () => {
    const missing = fields.find((f) => f.required && !values[f.key])
    if (missing) { setError(`${missing.label}: ${t('errors.requiredField')}`); return }
    setError(undefined)
    const body: Record<string, unknown> = { vehicle }
    for (const f of fields) {
      const v = values[f.key]
      if (f.type === 'checkbox') body[f.key] = v
      else if (v !== '' && v !== undefined) body[f.key] = f.type === 'number' ? Number(v) : v
    }
    create.mutate(body, {
      onSuccess: () => { setValues(initialValues(fields)) },
      onError: (e) => { setError(errorMessage(e, t)) },
    })
  }

  return (
    <div className="space-y-3">
      {header}
      {list.isError ? <p role="alert" className="text-sm text-red-600">{errorMessage(list.error, t)}</p> : null}
      {list.data && list.data.results.length === 0 ? <p className="text-sm text-muted">{emptyText}</p> : null}
      <ul className="divide-y divide-slate-200 text-sm">
        {list.data?.results.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 py-1.5">
            <span>{summary(row)}</span>
            {readOnly ? null : (
              <WriteButton permission="fleet.delete" variant="ghost" aria-label={t('fleet.deleteRecord')} onClick={() => { remove.mutate(row.id) }}>
                {t('common.delete')}
              </WriteButton>
            )}
          </li>
        ))}
      </ul>
      {readOnly ? null : (
        <div className="grid grid-cols-2 gap-2">
          {fields.map((f) => {
            const common = { label: f.label, key: f.key }
            const v = values[f.key]
            if (f.type === 'select') {
              return <Select {...common} value={String(v)} options={f.options ?? []} onChange={(x) => { setValues((s) => ({ ...s, [f.key]: x })) }} />
            }
            if (f.type === 'checkbox') {
              return <Checkbox key={f.key} label={f.label} checked={Boolean(v)} onChange={(e) => { setValues((s) => ({ ...s, [f.key]: e.target.checked })) }} />
            }
            if (f.type === 'date' || f.type === 'datetime') {
              return <DateInput {...common} withTime={f.type === 'datetime'} value={String(v)} onChange={(x) => { setValues((s) => ({ ...s, [f.key]: x })) }} />
            }
            return (
              <TextField {...common} inputMode={f.type === 'number' ? 'decimal' : undefined} value={String(v)} onChange={(e) => { setValues((s) => ({ ...s, [f.key]: e.target.value })) }} />
            )
          })}
          <div className="col-span-2">
            <WriteButton permission="fleet.create" onClick={submit} disabled={create.isPending}>{t('fleet.add')}</WriteButton>
          </div>
        </div>
      )}
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
    </div>
  )
}
