import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { TripFields, defaultCurrency, validateTrip, type TripFormState } from '../../trips/components/TripFields'
import { useCreateTrip } from '../../trips/hooks'
import type { Consignment } from '../types'

const KNOWN = /^(carrier|vehicle_plate|driver_name|price|currency|consignments)$/

interface Props {
  selected: Consignment[]
  onClose: () => void
  onCreated: () => void
}

/** Создание рейса на выбранные грузы; грузы нескольких заказов дают сборный рейс. */
export function CreateTripDrawer({ selected, onClose, onCreated }: Props) {
  const { t } = useTranslation()
  const currencies = useHandbookValues('currency', { activeOnly: true })
  const create = useCreateTrip()
  const formRef = useRef<HTMLFormElement>(null)
  const [form, setForm] = useState<TripFormState>({ carrier: null, vehicle_plate: '', driver_name: '', price: '0', currency: '' })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  useFocusInvalid(formRef, errors)

  const orderCount = new Set(selected.map((c) => c.order)).size
  const currency = form.currency || defaultCurrency(currencies.values)

  const submit = () => {
    const local = validateTrip(form, t)
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    create.mutate(
      {
        consignments: selected.map((c) => c.id),
        carrier: form.carrier?.id ?? null,
        vehicle_plate: form.vehicle_plate.trim(),
        driver_name: form.driver_name.trim(),
        price: form.price.trim(),
        ...(currency ? { currency: Number(currency) } : {}),
      },
      {
        onSuccess: (trip) => {
          pushToast('info', t('trips.created', { number: trip.number }), {
            label: t('trips.openTrip'),
            to: `/trips?q=${encodeURIComponent(trip.number)}`,
          })
          onCreated()
        },
        onError: (error) => { setErrors(serverErrors(error, t, (path) => KNOWN.test(path))) },
      },
    )
  }

  return (
    <Drawer
      open
      title={t('consignments.createTrip')}
      onClose={onClose}
      busy={create.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission="trips.create" variant="primary" onClick={submit} disabled={create.isPending || selected.length === 0}>
            {create.isPending ? t('common.saving') : t('trips.create')}
          </WriteButton>
        </>
      }
    >
      <form ref={formRef} noValidate className="space-y-3" onSubmit={(event) => { event.preventDefault(); submit() }}>
        <FormBanner message={errors.banner} />
        {orderCount > 1 ? <Banner kind="warning">{t('trips.consolidationNotice')}</Banner> : null}
        <TripFields
          form={{ ...form, currency }}
          errors={errors.fields}
          currencies={currencies.values}
          onChange={(key, value) => { setForm((f) => ({ ...f, [key]: value })) }}
        />
        <section aria-labelledby="trip-cargo-title">
          <h3 id="trip-cargo-title" className="mb-1 text-xs font-medium text-slate-600 dark:text-slate-300">
            {t('consignments.selectedCargo', { count: selected.length })}
          </h3>
          {errors.fields.consignments ? <p role="alert" className="mb-1 text-xs text-red-600">{errors.fields.consignments}</p> : null}
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-700">
            {selected.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-x-3 px-2 py-1">
                <span className="font-medium">{c.name}</span>
                <Link to={`/orders/${String(c.order)}`} className="text-brand-700 hover:underline dark:text-brand-300">
                  {c.order_number}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </form>
    </Drawer>
  )
}
