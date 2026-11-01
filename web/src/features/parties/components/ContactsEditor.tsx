import { useTranslation } from 'react-i18next'
import { Button } from '../../../shared/ui/Button'
import { TextField } from '../../../shared/ui/TextField'

export interface ContactRow {
  key: string
  id?: number
  name: string
  position: string
  phone: string
  email: string
}

let counter = 0
export function newContactRow(partial: Partial<ContactRow> = {}): ContactRow {
  counter += 1
  return { key: `c${counter}`, name: '', position: '', phone: '', email: '', ...partial }
}

interface Props {
  rows: ContactRow[]
  onChange: (rows: ContactRow[]) => void
  /** Ошибки по путям формы: "contacts.0.name", "contacts". */
  errors: Record<string, string>
  disabled?: boolean
}

/** Редактор контактов: добавить, изменить, убрать строку. Ошибки сервера - у своей строки и поля. */
export function ContactsEditor({ rows, onChange, errors, disabled }: Props) {
  const { t } = useTranslation()
  const patch = (index: number, change: Partial<ContactRow>) => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...change } : row)))
  }
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-xs font-semibold uppercase text-slate-500">{t('parties.contacts')}</legend>
      {errors.contacts ? (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {errors.contacts}
        </p>
      ) : null}
      {rows.length === 0 ? <p className="text-xs text-slate-500">{t('parties.noContacts')}</p> : null}
      {rows.map((row, index) => (
        <div key={row.key} className="grid grid-cols-1 gap-2 rounded border border-slate-200 p-2 sm:grid-cols-2 dark:border-slate-700">
          <TextField
            label={t('parties.contactName')}
            required
            value={row.name}
            error={errors[`contacts.${index}.name`]}
            onChange={(event) => {
              patch(index, { name: event.target.value })
            }}
          />
          <TextField
            label={t('parties.contactPosition')}
            value={row.position}
            error={errors[`contacts.${index}.position`]}
            onChange={(event) => {
              patch(index, { position: event.target.value })
            }}
          />
          <TextField
            label={t('parties.contactPhone')}
            type="tel"
            value={row.phone}
            error={errors[`contacts.${index}.phone`]}
            onChange={(event) => {
              patch(index, { phone: event.target.value })
            }}
          />
          <TextField
            label={t('parties.contactEmail')}
            type="email"
            value={row.email}
            error={errors[`contacts.${index}.email`]}
            onChange={(event) => {
              patch(index, { email: event.target.value })
            }}
          />
          <div className="sm:col-span-2">
            <Button
              variant="ghost"
              aria-label={t('parties.removeContact', { n: index + 1 })}
              onClick={() => {
                onChange(rows.filter((_, i) => i !== index))
              }}
            >
              {t('common.remove')}
            </Button>
          </div>
        </div>
      ))}
      <Button
        onClick={() => {
          onChange([...rows, newContactRow()])
        }}
      >
        {t('parties.addContact')}
      </Button>
    </fieldset>
  )
}
