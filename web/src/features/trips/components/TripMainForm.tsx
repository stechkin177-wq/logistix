import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { usePatchTrip } from '../hooks'
import type { Trip } from '../types'
import { TripFields, validateTrip, type TripFormState } from './TripFields'

const KNOWN = /^(carrier|contract|vehicle|trailer|driver|vehicle_plate|driver_name|carrier_price|currency)$/

/** Основные поля рейса: перевозчик, техника, водитель, цена. Сохранение - PATCH только редактируемых полей. */
export function TripMainForm({ trip }: { trip: Trip }) {
  const { t } = useTranslation()
  const currencies = useHandbookValues('currency')
  const canUpdate = useCanWrite('trips.update')
  const patch = usePatchTrip()
  const formRef = useRef<HTMLFormElement>(null)
  const [form, setForm] = useState<TripFormState>({
    carrier: trip.carrier !== null ? { id: trip.carrier, label: trip.carrier_name ?? `#${String(trip.carrier)}` } : null,
    vehicle: trip.vehicle ? { id: trip.vehicle, label: trip.vehicle_plate || `#${String(trip.vehicle)}` } : null,
    trailer: trip.trailer ? { id: trip.trailer, label: `#${String(trip.trailer)}` } : null,
    driver: trip.driver ? { id: trip.driver, label: trip.driver_name || `#${String(trip.driver)}` } : null,
    vehicle_plate: trip.vehicle_plate,
    driver_name: trip.driver_name,
    carrier_price: trip.carrier_price,
    currency: String(trip.currency),
    contract: trip.contract ? String(trip.contract) : '',
  })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  useFocusInvalid(formRef, errors)

  const submit = () => {
    const local = validateTrip(form, t)
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    // PATCH несёт только редактируемые поля: номер, статус, грузы и is_consolidated сервер отвергает
    patch.mutate(
      {
        id: trip.id,
        body: {
          carrier: form.carrier?.id ?? null,
          // ссылки уходят только при изменении: лишняя проверка занятости не нужна
          ...((form.vehicle?.id ?? null) !== (trip.vehicle ?? null) ? { vehicle: form.vehicle?.id ?? null } : {}),
          ...((form.trailer?.id ?? null) !== (trip.trailer ?? null) ? { trailer: form.trailer?.id ?? null } : {}),
          ...((form.driver?.id ?? null) !== (trip.driver ?? null) ? { driver: form.driver?.id ?? null } : {}),
          ...(form.vehicle === null ? { vehicle_plate: form.vehicle_plate.trim() } : {}),
          ...(form.driver === null ? { driver_name: form.driver_name.trim() } : {}),
          // договор уходит только при изменении (смена перевозчика снимает его и на сервере)
          ...(form.contract !== (trip.contract ? String(trip.contract) : '') ? { contract: form.contract ? Number(form.contract) : null } : {}),
          carrier_price: form.carrier_price.trim(),
          ...(form.currency ? { currency: Number(form.currency) } : {}),
        },
      },
      { onError: (error) => { setErrors(serverErrors(error, t, (path) => KNOWN.test(path))) } },
    )
  }

  return (
    <form ref={formRef} noValidate className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (canUpdate) submit() }}>
      <FormBanner message={errors.banner} />
      <TripFields
        form={form}
        errors={errors.fields}
        currencies={currencies.values.filter((c) => c.is_active || c.id === trip.currency)}
        disabled={!canUpdate}
        withContract
        onChange={(key, value) => { setForm((f) => ({ ...f, [key]: value })) }}
      />
      <div className="flex justify-end">
        <WriteButton permission="trips.update" variant="primary" type="submit" disabled={patch.isPending}>
          {patch.isPending ? t('common.saving') : t('common.save')}
        </WriteButton>
      </div>
    </form>
  )
}
