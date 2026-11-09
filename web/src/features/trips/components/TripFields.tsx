import { useTranslation } from 'react-i18next'
import type { HandbookValue } from '../../../shared/api/types'
import { Combobox, type ComboOption } from '../../../shared/ui/Combobox'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { useSession } from '../../../shared/auth/useSession'
import { searchActiveCarriers, searchDrivers, searchVehicles } from '../api'

export interface TripFormState {
  carrier: ComboOption | null
  vehicle: ComboOption | null
  trailer: ComboOption | null
  driver: ComboOption | null
  vehicle_plate: string
  driver_name: string
  carrier_price: string
  currency: string
}

const MONEY_RE = /^\d{1,12}(\.\d{1,2})?$/

export function validateTrip(form: TripFormState, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!MONEY_RE.test(form.carrier_price.trim())) errors.carrier_price = t('errors.invalidNumber')
  return errors
}

/** Поля, общие для создания и правки рейса (перевозчик, машина, водитель, цена, валюта). */
export function TripFields({ form, errors, currencies, disabled, onChange }: {
  form: TripFormState
  errors: Record<string, string>
  currencies: HandbookValue[]
  disabled?: boolean
  onChange: <K extends keyof TripFormState>(key: K, value: TripFormState[K]) => void
}) {
  const { t } = useTranslation()
  const { hasModule, hasPermission } = useSession()
  // справочники техники и водителей - если модули включены и есть право просмотра; иначе только текст
  const fleet = hasModule('fleet') && hasPermission('fleet.view')
  const drivers = hasModule('drivers') && hasPermission('drivers.view')
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <Combobox
        label={t('trips.carrier')}
        queryKey={['carriers', 'search-active']}
        fetchOptions={searchActiveCarriers}
        value={form.carrier}
        disabled={disabled}
        error={errors.carrier}
        fieldClassName="sm:col-span-2"
        onChange={(option) => { onChange('carrier', option) }}
      />
      {fleet ? (
        <>
          <Combobox label={t('trips.vehicle')} queryKey={['vehicles', 'search-trip']} fetchOptions={(q, signal) => searchVehicles(q, signal)} value={form.vehicle} disabled={disabled} error={errors.vehicle} onChange={(o) => { onChange('vehicle', o) }} />
          <Combobox label={t('trips.trailer')} queryKey={['vehicles', 'search-trailer']} fetchOptions={(q, signal) => searchVehicles(q, signal, 'trailer')} value={form.trailer} disabled={disabled} error={errors.trailer} onChange={(o) => { onChange('trailer', o) }} />
        </>
      ) : null}
      {/* выбранная техника/водитель заполняют текст на сервере: свободное поле тогда не нужно */}
      {form.vehicle === null ? (
        <TextField label={t('trips.vehiclePlate')} value={form.vehicle_plate} disabled={disabled} error={errors.vehicle_plate} maxLength={32} onChange={(e) => { onChange('vehicle_plate', e.target.value) }} />
      ) : null}
      {drivers ? (
        <Combobox label={t('trips.driver')} queryKey={['drivers', 'search-trip']} fetchOptions={searchDrivers} value={form.driver} disabled={disabled} error={errors.driver} onChange={(o) => { onChange('driver', o) }} />
      ) : null}
      {form.driver === null ? (
        <TextField label={t('trips.driverName')} value={form.driver_name} disabled={disabled} error={errors.driver_name} maxLength={255} onChange={(e) => { onChange('driver_name', e.target.value) }} />
      ) : null}
      <TextField label={t('trips.carrierPrice')} inputMode="decimal" value={form.carrier_price} disabled={disabled} error={errors.carrier_price} onChange={(e) => { onChange('carrier_price', e.target.value) }} />
      <Select
        label={t('trips.currency')}
        value={form.currency}
        disabled={disabled}
        error={errors.currency}
        placeholder={currencies.length === 0 ? t('common.none') : undefined}
        options={currencies.map((c) => ({ value: String(c.id), label: c.code ? `${c.code} - ${c.name}` : c.name }))}
        onChange={(v) => { onChange('currency', v) }}
      />
    </div>
  )
}

/** Валюта по умолчанию: KZT, если есть; иначе первая активная. */
export function defaultCurrency(currencies: HandbookValue[]): string {
  const kzt = currencies.find((c) => c.code === 'KZT')
  return String((kzt ?? currencies[0])?.id ?? '')
}
