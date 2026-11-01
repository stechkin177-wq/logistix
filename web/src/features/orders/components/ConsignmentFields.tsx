import { useTranslation } from 'react-i18next'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { DateInput } from '../../../shared/ui/DateInput'
import { Select } from '../../../shared/ui/Select'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import type { HandbookValue } from '../../../shared/api/types'
import type { ConsignmentForm, PointForm } from '../orderForm'

interface Props {
  value: ConsignmentForm
  onChange: (value: ConsignmentForm) => void
  /** Префикс путей ошибок: "consignments.0." в форме заказа, "" в карточке груза. */
  prefix: string
  errors: Record<string, string>
  disabled?: boolean
}

/** Поля груза (блок «Груз»). */
export function CargoFields({ value, onChange, prefix, errors, disabled }: Props) {
  const { t } = useTranslation()
  const packaging = useHandbookValues('packaging')
  const err = (path: string) => errors[`${prefix}${path}`]
  const patch = (change: Partial<ConsignmentForm>) => { onChange({ ...value, ...change }) }
  return (
    <fieldset disabled={disabled}>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <TextField fieldClassName="col-span-2" label={t('orders.cargoName')} required value={value.name} error={err('name')} onChange={(e) => { patch({ name: e.target.value }) }} />
        <TextField label={t('orders.weightKg')} required inputMode="decimal" value={value.weight_kg} error={err('weight_kg')} onChange={(e) => { patch({ weight_kg: e.target.value }) }} />
        <TextField label={t('orders.volumeM3')} required inputMode="decimal" value={value.volume_m3} error={err('volume_m3')} onChange={(e) => { patch({ volume_m3: e.target.value }) }} />
        <TextField label={t('orders.pallets')} inputMode="numeric" value={value.pallets} error={err('pallets')} onChange={(e) => { patch({ pallets: e.target.value }) }} />
        <Select fieldClassName="col-span-2 md:col-span-1" label={t('orders.packaging')} value={value.packaging} placeholder={t('common.none')} options={handbookOptions(packaging.all, value.packaging)} error={err('packaging')} onChange={(v) => { patch({ packaging: v }) }} />
      </div>
    </fieldset>
  )
}

function handbookOptions(all: HandbookValue[], current: string) {
  return selectableValues(all, current ? Number(current) : null).map((v) => ({ value: String(v.id), label: v.name }))
}

/** Точки погрузки и выгрузки (блок «Маршрут»). */
export function RouteFields({ value, onChange, prefix, errors, disabled }: Props) {
  const { t } = useTranslation()
  const countries = useHandbookValues('country')
  const methods = useHandbookValues('loading_method')
  const err = (path: string) => errors[`${prefix}${path}`]
  const patchPoint = (index: 0 | 1, change: Partial<PointForm>) => {
    const points: [PointForm, PointForm] = [value.points[0], value.points[1]]
    points[index] = { ...points[index], ...change }
    onChange({ ...value, points })
  }
  const options = handbookOptions
  return (
    <fieldset disabled={disabled} className="space-y-2">
      {err('points') ? <p role="alert" className="text-xs text-red-600 dark:text-red-400">{err('points')}</p> : null}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {([0, 1] as const).map((index) => {
          const point = value.points[index]
          const base = `points.${String(index)}.`
          const title = t(index === 0 ? 'orders.loadPoint' : 'orders.unloadPoint')
          return (
            <section key={index} aria-label={title} className="space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700">
              <h4 className="text-xs font-semibold uppercase text-slate-500">{title}</h4>
              <div className="grid grid-cols-2 gap-2">
                <DateInput withTime label={t('orders.windowFrom')} required value={point.window_from} error={err(`${base}window_from`)} onChange={(v) => { patchPoint(index, { window_from: v }) }} />
                <DateInput withTime label={t('orders.windowTo')} value={point.window_to} error={err(`${base}window_to`)} onChange={(v) => { patchPoint(index, { window_to: v }) }} />
                <Select label={t('orders.country')} value={point.country} placeholder={t('common.none')} options={options(countries.all, point.country)} error={err(`${base}country`)} onChange={(v) => { patchPoint(index, { country: v }) }} />
                <TextField label={t('orders.city')} required value={point.city} error={err(`${base}city`)} onChange={(e) => { patchPoint(index, { city: e.target.value }) }} />
                <TextField fieldClassName="col-span-2" label={t('orders.street')} value={point.street} error={err(`${base}street`)} onChange={(e) => { patchPoint(index, { street: e.target.value }) }} />
                <Select label={t('orders.method')} value={point.method} placeholder={t('common.none')} options={options(methods.all, point.method)} error={err(`${base}method`)} onChange={(v) => { patchPoint(index, { method: v }) }} />
                <TextField label={t('orders.pointContact')} value={point.contact} error={err(`${base}contact`)} onChange={(e) => { patchPoint(index, { contact: e.target.value }) }} />
                <TextField label={t('orders.postalCode')} value={point.postal_code} error={err(`${base}postal_code`)} onChange={(e) => { patchPoint(index, { postal_code: e.target.value }) }} />
                <div className="grid grid-cols-2 gap-2">
                  <TextField label={t('orders.lat')} inputMode="decimal" value={point.lat} error={err(`${base}lat`)} onChange={(e) => { patchPoint(index, { lat: e.target.value }) }} />
                  <TextField label={t('orders.lng')} inputMode="decimal" value={point.lng} error={err(`${base}lng`)} onChange={(e) => { patchPoint(index, { lng: e.target.value }) }} />
                </div>
                <TextArea fieldClassName="col-span-2" label={t('orders.pointNote')} value={point.note} error={err(`${base}note`)} onChange={(e) => { patchPoint(index, { note: e.target.value }) }} />
              </div>
            </section>
          )
        })}
      </div>
    </fieldset>
  )
}

/** Груз и маршрут вместе (карточка груза на вкладке «Грузы»). */
export function ConsignmentFields(props: Props) {
  return (
    <div className="space-y-3">
      <CargoFields {...props} />
      <RouteFields {...props} />
    </div>
  )
}
