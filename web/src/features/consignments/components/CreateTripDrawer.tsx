import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Banner } from '../../../shared/ui/Banner'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { Button } from '../../../shared/ui/Button'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { TripFields, defaultCurrency, validateTrip, type TripFormState } from '../../trips/components/TripFields'
import { useCreateTrip } from '../../trips/hooks'
import type { TripLegInput } from '../../trips/types'
import type { Consignment } from '../types'

const KNOWN = /^(carrier|vehicle|trailer|driver|vehicle_plate|driver_name|carrier_price|currency|consignments|legs)$/

/** Выбор участка для груза с несколькими остановками (необязателен: по умолчанию весь маршрут). */
interface LegPick {
  on: boolean
  from: string
  to: string
  weight: string
  volume: string
  pallets: string
}

const hasRoute = (c: Consignment) => (c.stops?.length ?? 0) > 2

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
  const [form, setForm] = useState<TripFormState>({ carrier: null, vehicle: null, trailer: null, driver: null, vehicle_plate: '', driver_name: '', carrier_price: '0', currency: '' })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const [picks, setPicks] = useState<Record<number, LegPick>>({})
  useFocusInvalid(formRef, errors)

  const pickOf = (c: Consignment): LegPick => {
    const stops = c.stops ?? []
    return picks[c.id] ?? { on: false, from: String(stops[0]?.id ?? ''), to: String(stops[stops.length - 1]?.id ?? ''), weight: '', volume: '', pallets: '' }
  }
  const setPick = (c: Consignment, change: Partial<LegPick>) => { setPicks((prev) => ({ ...prev, [c.id]: { ...pickOf(c), ...change } })) }

  const orderCount = new Set(selected.map((c) => c.order)).size
  const currency = form.currency || defaultCurrency(currencies.values)

  const submit = () => {
    const local = validateTrip(form, t)
    const legs: TripLegInput[] = []
    for (const c of selected) {
      const pick = pickOf(c)
      if (!hasRoute(c) || !pick.on) continue
      const seqOf = (id: string) => c.stops?.find((st) => String(st.id) === id)?.seq ?? 0
      if (seqOf(pick.from) >= seqOf(pick.to)) local.legs = t('trips.legOrder')
      const shares = {
        ...(pick.weight.trim() ? { weight_kg: pick.weight.trim() } : {}),
        ...(pick.volume.trim() ? { volume_m3: pick.volume.trim() } : {}),
        ...(pick.pallets.trim() ? { pallets: Number(pick.pallets.trim()) } : {}),
      }
      legs.push({ consignment: c.id, from_stop: Number(pick.from), to_stop: Number(pick.to), ...(Object.keys(shares).length > 0 ? { shares } : {}) })
    }
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    create.mutate(
      {
        // грузы с явными участками уходят в legs, остальные - на весь маршрут
        consignments: selected.filter((c) => !legs.some((l) => l.consignment === c.id)).map((c) => c.id),
        ...(legs.length > 0 ? { legs } : {}),
        carrier: form.carrier?.id ?? null,
        ...(form.vehicle ? { vehicle: form.vehicle.id } : { vehicle_plate: form.vehicle_plate.trim() }),
        ...(form.trailer ? { trailer: form.trailer.id } : {}),
        ...(form.driver ? { driver: form.driver.id } : { driver_name: form.driver_name.trim() }),
        carrier_price: form.carrier_price.trim(),
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
          {errors.fields.legs ? <p role="alert" className="mb-1 text-xs text-red-600">{errors.fields.legs}</p> : null}
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-700">
            {selected.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-x-3 px-2 py-1">
                <span className="font-medium">{c.name}</span>
                <Link to={`/orders/${String(c.order)}`} className="text-brand-700 hover:underline dark:text-brand-300">
                  {c.order_number}
                </Link>
                {hasRoute(c) ? <LegPicker cargo={c} pick={pickOf(c)} onChange={(change) => { setPick(c, change) }} /> : null}
              </li>
            ))}
          </ul>
        </section>
      </form>
    </Drawer>
  )
}

function LegPicker({ cargo, pick, onChange }: { cargo: Consignment; pick: LegPick; onChange: (change: Partial<LegPick>) => void }) {
  const { t } = useTranslation()
  const options = (cargo.stops ?? []).map((st) => ({
    value: String(st.id),
    label: t('trips.legStopLabel', { seq: st.seq, city: st.city, kind: t(`orders.stopKinds.${st.kind}`) }),
  }))
  return (
    <div className="basis-full space-y-1 py-1">
      <Checkbox label={t('trips.pickLegs')} checked={pick.on} onChange={(e) => { onChange({ on: e.target.checked }) }} />
      {pick.on ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          <Select label={t('trips.legFrom')} value={pick.from} options={options} onChange={(v) => { onChange({ from: v }) }} />
          <Select label={t('trips.legTo')} value={pick.to} options={options} onChange={(v) => { onChange({ to: v }) }} />
          <p className="col-span-2 text-xs text-slate-500 md:col-span-3">{t('trips.legSharesHint')}</p>
          <TextField label={t('trips.legWeight')} inputMode="decimal" value={pick.weight} onChange={(e) => { onChange({ weight: e.target.value }) }} />
          <TextField label={t('trips.legVolume')} inputMode="decimal" value={pick.volume} onChange={(e) => { onChange({ volume: e.target.value }) }} />
          <TextField label={t('trips.legPallets')} inputMode="numeric" value={pick.pallets} onChange={(e) => { onChange({ pallets: e.target.value }) }} />
        </div>
      ) : null}
    </div>
  )
}
