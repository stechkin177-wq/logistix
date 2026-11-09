import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { DateInput } from '../../../shared/ui/DateInput'
import { Select } from '../../../shared/ui/Select'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import type { HandbookValue } from '../../../shared/api/types'
import { Button } from '../../../shared/ui/Button'
import { canSimplify, emptyStop, toStops, type ConsignmentForm, type PointForm, type StopForm } from '../orderForm'
import type { StopKind } from '../types'

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

interface PointFieldsProps {
  point: PointForm
  base: string
  err: (path: string) => string | undefined
  patch: (change: Partial<PointForm>) => void
  /** Простой режим: дата, город и адрес; остальное - в раскрываемом «Подробнее». */
  compact?: boolean
}

const DETAIL_KEYS = ['window_to', 'country', 'method', 'contact', 'postal_code', 'lat', 'lng', 'note'] as const

/** Поля одной точки маршрута (окно, адрес, способ, контакт, координаты). */
function PointFields({ point, base, err, patch, compact }: PointFieldsProps) {
  const { t } = useTranslation()
  const countries = useHandbookValues('country')
  const methods = useHandbookValues('loading_method')
  const [open, setOpen] = useState(false)
  // подробности открыты сами, если в них уже есть значения или ошибки проверки
  const showDetails = !compact || open || DETAIL_KEYS.some((k) => point[k] !== '' || err(`${base}${k}`))
  return (
    <div className="grid grid-cols-2 gap-2">
      <DateInput withTime label={t('orders.windowFrom')} required value={point.window_from} error={err(`${base}window_from`)} onChange={(v) => { patch({ window_from: v }) }} />
      <TextField label={t('orders.city')} required value={point.city} error={err(`${base}city`)} onChange={(e) => { patch({ city: e.target.value }) }} />
      <TextField fieldClassName="col-span-2" label={t('orders.street')} value={point.street} error={err(`${base}street`)} onChange={(e) => { patch({ street: e.target.value }) }} />
      {compact ? (
        <div className="col-span-2">
          <Button variant="ghost" aria-expanded={showDetails} onClick={() => { setOpen(!showDetails) }}>
            {showDetails ? '▾' : '▸'} {t('orders.pointDetails')}
          </Button>
        </div>
      ) : null}
      {showDetails ? <PointDetails point={point} base={base} err={err} patch={patch} countries={countries.all} methods={methods.all} /> : null}
    </div>
  )
}

function PointDetails({ point, base, err, patch, countries, methods }: Omit<PointFieldsProps, 'compact'> & { countries: HandbookValue[]; methods: HandbookValue[] }) {
  const { t } = useTranslation()
  return (
    <>
      <DateInput withTime label={t('orders.windowTo')} value={point.window_to} error={err(`${base}window_to`)} onChange={(v) => { patch({ window_to: v }) }} />
      <Select label={t('orders.country')} value={point.country} placeholder={t('common.none')} options={handbookOptions(countries, point.country)} error={err(`${base}country`)} onChange={(v) => { patch({ country: v }) }} />
      <Select label={t('orders.method')} value={point.method} placeholder={t('common.none')} options={handbookOptions(methods, point.method)} error={err(`${base}method`)} onChange={(v) => { patch({ method: v }) }} />
      <TextField label={t('orders.pointContact')} value={point.contact} error={err(`${base}contact`)} onChange={(e) => { patch({ contact: e.target.value }) }} />
      <TextField label={t('orders.postalCode')} value={point.postal_code} error={err(`${base}postal_code`)} onChange={(e) => { patch({ postal_code: e.target.value }) }} />
      <div className="grid grid-cols-2 gap-2">
        <TextField label={t('orders.lat')} inputMode="decimal" value={point.lat} error={err(`${base}lat`)} onChange={(e) => { patch({ lat: e.target.value }) }} />
        <TextField label={t('orders.lng')} inputMode="decimal" value={point.lng} error={err(`${base}lng`)} onChange={(e) => { patch({ lng: e.target.value }) }} />
      </div>
      <TextArea fieldClassName="col-span-2" label={t('orders.pointNote')} value={point.note} error={err(`${base}note`)} onChange={(e) => { patch({ note: e.target.value }) }} />
    </>
  )
}

const STOP_KINDS: StopKind[] = ['load', 'transit', 'transfer', 'customs', 'unload']

/** Редактор расширенного маршрута: остановки по порядку (вид, адрес, окно, доли), порядок и состав меняются. */
function StopsEditor({ value, onChange, prefix, errors }: Props & { value: ConsignmentForm & { stops: StopForm[] } }) {
  const { t } = useTranslation()
  const err = (path: string) => errors[`${prefix}${path}`]
  const stops = value.stops
  const setStops = (next: StopForm[]) => { onChange({ ...value, stops: next }) }
  const patchStop = (index: number, change: Partial<StopForm>) => {
    setStops(stops.map((st, i) => (i === index ? { ...st, ...change } : st)))
  }
  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= stops.length) return
    const moved = stops[index]
    const other = stops[target]
    if (!moved || !other) return
    const next = [...stops]
    next[index] = other
    next[target] = moved
    setStops(next)
  }
  const add = () => {
    // новая промежуточная остановка встаёт перед последней (выгрузкой)
    const next = [...stops]
    next.splice(Math.max(stops.length - 1, 0), 0, emptyStop('transit'))
    setStops(next)
  }
  const kindOptions = STOP_KINDS.map((k) => ({ value: k, label: t(`orders.stopKinds.${k}`) }))
  return (
    <div className="space-y-2">
      {err('stops') ? <p role="alert" className="text-xs text-red-600 dark:text-red-400">{err('stops')}</p> : null}
      <ol className="space-y-2">
        {stops.map((stop, index) => {
          const base = `stops.${String(index)}.`
          const title = t('orders.stopN', { n: index + 1 })
          return (
            <li key={stop.key}>
              <section aria-label={title} className="space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700">
                <div className="flex flex-wrap items-end justify-between gap-2">
                  <h4 className="text-xs font-semibold uppercase text-slate-500">{title}</h4>
                  <div className="flex items-end gap-1">
                    <Select label={t('orders.stopKind')} value={stop.kind} options={kindOptions} error={err(`${base}kind`)} onChange={(v) => { patchStop(index, { kind: v as StopKind }) }} />
                    <Button variant="ghost" aria-label={t('orders.moveStopUp', { n: index + 1 })} disabled={index === 0} onClick={() => { move(index, -1) }}>↑</Button>
                    <Button variant="ghost" aria-label={t('orders.moveStopDown', { n: index + 1 })} disabled={index === stops.length - 1} onClick={() => { move(index, 1) }}>↓</Button>
                    <Button variant="ghost" aria-label={t('orders.removeStopN', { n: index + 1 })} disabled={stops.length <= 2} onClick={() => { setStops(stops.filter((_, i) => i !== index)) }}>
                      {t('common.delete')}
                    </Button>
                  </div>
                </div>
                <PointFields point={stop} base={base} err={err} patch={(change) => { patchStop(index, change) }} />
                <fieldset className="grid grid-cols-3 gap-2">
                  <legend className="text-xs text-slate-500">{t('orders.stopShares')} — {t('orders.stopSharesHint')}</legend>
                  <TextField label={t('orders.weightKg')} inputMode="decimal" value={stop.weight_kg} error={err(`${base}weight_kg`)} onChange={(e) => { patchStop(index, { weight_kg: e.target.value }) }} />
                  <TextField label={t('orders.volumeM3')} inputMode="decimal" value={stop.volume_m3} error={err(`${base}volume_m3`)} onChange={(e) => { patchStop(index, { volume_m3: e.target.value }) }} />
                  <TextField label={t('orders.pallets')} inputMode="numeric" value={stop.pallets} error={err(`${base}pallets`)} onChange={(e) => { patchStop(index, { pallets: e.target.value }) }} />
                </fieldset>
              </section>
            </li>
          )
        })}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button onClick={add}>{t('orders.addStop')}</Button>
        <Button variant="ghost" disabled={!canSimplify(stops)} onClick={() => {
          const [first, second] = stops
          if (first && second) onChange({ ...value, points: [first, second], stops: null })
        }}>
          {t('orders.simpleRoute')}
        </Button>
      </div>
    </div>
  )
}

/** Маршрут: по умолчанию погрузка и выгрузка (points), по кнопке - несколько остановок (stops). */
export function RouteFields({ value, onChange, prefix, errors, disabled }: Props) {
  const { t } = useTranslation()
  const err = (path: string) => errors[`${prefix}${path}`]
  const stops = value.stops
  if (stops !== null) {
    return (
      <fieldset disabled={disabled}>
        <StopsEditor value={{ ...value, stops }} onChange={onChange} prefix={prefix} errors={errors} />
      </fieldset>
    )
  }
  const patchPoint = (index: 0 | 1, change: Partial<PointForm>) => {
    const points: [PointForm, PointForm] = [value.points[0], value.points[1]]
    points[index] = { ...points[index], ...change }
    onChange({ ...value, points })
  }
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
              <PointFields compact point={point} base={base} err={err} patch={(change) => { patchPoint(index, change) }} />
            </section>
          )
        })}
      </div>
      <Button onClick={() => { onChange({ ...value, stops: toStops(value) }) }}>{t('orders.multiStops')}</Button>
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
