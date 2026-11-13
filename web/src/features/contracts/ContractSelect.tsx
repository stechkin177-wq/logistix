import { useTranslation } from 'react-i18next'
import { useFormat } from '../../shared/format/useFormat'
import { Select } from '../../shared/ui/Select'
import { useContracts } from './hooks'
import type { PartyOwner } from './types'

/** Выбор договора из реестра стороны (клиента заказа или перевозчика рейса). Без стороны - не показывается. */
export function ContractSelect({
  owner, value, onChange, disabled, error, label, fieldClassName, currentLabel,
}: {
  owner: PartyOwner | null
  value: string
  onChange: (value: string, contract?: { id: number; number: string }) => void
  disabled?: boolean
  error?: string
  label?: string
  fieldClassName?: string
  /** Подпись уже выбранного договора, пока список не загрузился. */
  currentLabel?: string
}) {
  const { t } = useTranslation()
  const { date } = useFormat()
  const list = useContracts(owner, !disabled || value !== '')
  if (owner === null) return null
  const rows = list.data?.results ?? []
  const options = rows.map((c) => ({ value: String(c.id), label: `${c.number} · ${date(c.date)}${c.is_expired ? ` (${t('contracts.expired')})` : ''}` }))
  if (value !== '' && !options.some((o) => o.value === value)) options.push({ value, label: currentLabel ?? `#${value}` })
  return (
    <Select
      label={label ?? t('contracts.select')}
      value={value}
      placeholder={t('contracts.notSelected')}
      options={options}
      disabled={disabled}
      error={error}
      fieldClassName={fieldClassName}
      onChange={(v) => {
        const found = rows.find((c) => String(c.id) === v)
        onChange(v, found ? { id: found.id, number: found.number } : undefined)
      }}
    />
  )
}
