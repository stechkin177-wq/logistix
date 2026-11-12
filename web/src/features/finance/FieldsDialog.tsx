import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { Dialog } from '../../shared/ui/Dialog'
import { Select, type Option } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'

export interface FieldDef {
  key: string
  label: string
  type?: 'text' | 'date' | 'decimal' | 'select'
  options?: Option[]
  required?: boolean
  initial?: string
}

/**
 * Небольшая форма в диалоге: поля, защита от повторной отправки (кнопка отключается, пока идёт
 * запрос), ошибка сервера показывается в диалоге. Права скрывают кнопку (сервер проверяет).
 */
export function FieldsDialog({
  title, fields, submitLabel, permission, onSubmit, onClose, hint,
}: {
  title: string
  fields: FieldDef[]
  submitLabel: string
  permission?: string
  hint?: string
  onSubmit: (values: Record<string, string>) => Promise<unknown>
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((f) => [f.key, f.initial ?? ''])))
  const [error, setError] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const missing = fields.some((f) => f.required && !(values[f.key] ?? '').trim())

  const submit = () => {
    if (busy) return
    setBusy(true)
    setError(undefined)
    onSubmit(values).then(onClose, (e: unknown) => { setError(errorMessage(e, t)); setBusy(false) })
  }
  return (
    <Dialog
      open
      title={title}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission={permission} disabled={busy || missing} onClick={submit}>{submitLabel}</WriteButton>
        </>
      }
    >
      <div className="space-y-3">
        {error ? <Banner kind="error">{error}</Banner> : null}
        {hint ? <p className="text-sm text-muted">{hint}</p> : null}
        {fields.map((f) => {
          const set = (value: string) => { setValues((x) => ({ ...x, [f.key]: value })) }
          if (f.type === 'date') return <DateInput key={f.key} label={f.label} value={values[f.key] ?? ''} onChange={set} required={f.required} />
          if (f.type === 'select') {
            return <Select key={f.key} label={f.label} options={f.options ?? []} value={values[f.key] ?? ''} onChange={set} placeholder="—" required={f.required} />
          }
          return (
            <TextField
              key={f.key}
              label={f.label}
              inputMode={f.type === 'decimal' ? 'decimal' : undefined}
              value={values[f.key] ?? ''}
              onChange={(e) => { set(e.target.value) }}
              required={f.required}
            />
          )
        })}
      </div>
    </Dialog>
  )
}
