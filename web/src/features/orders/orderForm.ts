import { fromInputDateTime, toInputDateTime } from '../../shared/format/datetime'
import type { Order, OrderConsignment, OrderPoint } from './types'

export interface PointForm {
  window_from: string
  window_to: string
  country: string
  city: string
  street: string
  method: string
  contact: string
  postal_code: string
  lat: string
  lng: string
  note: string
}

export interface ConsignmentForm {
  key: string
  id?: number
  name: string
  weight_kg: string
  volume_m3: string
  pallets: string
  packaging: string
  /** [0] - погрузка, [1] - выгрузка: индексы совпадают с путями ошибок сервера (points.0 / points.1). */
  points: [PointForm, PointForm]
}

export interface OrderFormState {
  client: { id: number; label: string } | null
  client_ref: string
  contract_number: string
  contact: string
  manager: string
  forwarder: string
  extra_managers: number[]
  client_rate: string
  currency: string
  transport_condition: string
  delivery_days: string
  payment_delay_days: string
  payment_delay_condition: string
  comment: string
  consignments: ConsignmentForm[]
}

let counter = 0
const nextKey = () => `k${String((counter += 1))}`

export const emptyPoint = (): PointForm => ({
  window_from: '', window_to: '', country: '', city: '', street: '', method: '', contact: '', postal_code: '', lat: '', lng: '', note: '',
})

export const emptyConsignment = (): ConsignmentForm => ({
  key: nextKey(), name: '', weight_kg: '', volume_m3: '', pallets: '0', packaging: '', points: [emptyPoint(), emptyPoint()],
})

const idText = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

function pointFromApi(point: OrderPoint | undefined, tz: string | undefined): PointForm {
  if (!point) return emptyPoint()
  return {
    window_from: toInputDateTime(point.window_from, tz),
    window_to: toInputDateTime(point.window_to, tz),
    country: idText(point.country),
    city: point.city,
    street: point.street,
    method: idText(point.method),
    contact: point.contact,
    postal_code: point.postal_code,
    lat: point.lat ?? '',
    lng: point.lng ?? '',
    note: point.note,
  }
}

export function consignmentFromApi(c: OrderConsignment, tz: string | undefined): ConsignmentForm {
  return {
    key: nextKey(),
    id: c.id,
    name: c.name,
    weight_kg: c.weight_kg,
    volume_m3: c.volume_m3,
    pallets: String(c.pallets),
    packaging: idText(c.packaging),
    points: [
      pointFromApi(c.points.find((p) => p.kind === 'load'), tz),
      pointFromApi(c.points.find((p) => p.kind === 'unload'), tz),
    ],
  }
}

export function initialOrderState(order: Order | null, defaults: { manager?: number; currency?: number }): OrderFormState {
  return {
    client: order ? { id: order.client, label: order.client_name } : null,
    client_ref: order?.client_ref ?? '',
    contract_number: order?.contract_number ?? '',
    contact: idText(order?.contact),
    manager: order ? String(order.manager) : idText(defaults.manager),
    forwarder: idText(order?.forwarder),
    extra_managers: order?.extra_managers ?? [],
    client_rate: order?.client_rate ?? '0',
    currency: order ? String(order.currency) : idText(defaults.currency),
    transport_condition: idText(order?.transport_condition),
    delivery_days: idText(order?.delivery_days),
    payment_delay_days: idText(order?.payment_delay_days),
    payment_delay_condition: idText(order?.payment_delay_condition),
    comment: order?.comment ?? '',
    consignments: [],
  }
}

type Translate = (key: string) => string
const DECIMAL = /^\d{1,12}(\.\d{1,2})?$/
const COORD = /^-?\d{1,3}(\.\d{1,6})?$/
const INT = /^\d{1,9}$/

export function validateConsignment(c: ConsignmentForm, prefix: string, t: Translate, errors: Record<string, string>): void {
  const required = t('errors.requiredField')
  if (!c.name.trim()) errors[`${prefix}.name`] = required
  if (!c.weight_kg.trim()) errors[`${prefix}.weight_kg`] = required
  else if (!DECIMAL.test(c.weight_kg.trim())) errors[`${prefix}.weight_kg`] = t('errors.invalidNumber')
  if (!c.volume_m3.trim()) errors[`${prefix}.volume_m3`] = required
  else if (!DECIMAL.test(c.volume_m3.trim())) errors[`${prefix}.volume_m3`] = t('errors.invalidNumber')
  if (c.pallets.trim() && !INT.test(c.pallets.trim())) errors[`${prefix}.pallets`] = t('errors.invalidNumber')
  c.points.forEach((p, i) => {
    const base = `${prefix}.points.${String(i)}`
    if (!p.window_from) errors[`${base}.window_from`] = required
    if (!p.city.trim()) errors[`${base}.city`] = required
    if (p.window_from && p.window_to && p.window_to < p.window_from) errors[`${base}.window_to`] = t('orders.windowOrder')
    for (const key of ['lat', 'lng'] as const) {
      const value = p[key].trim()
      if (!value) continue
      const limit = key === 'lat' ? 90 : 180
      if (!COORD.test(value) || Math.abs(Number(value)) > limit) errors[`${base}.${key}`] = t('orders.coordRange')
    }
  })
}

/** Клиентская проверка зеркалит сервер; пути ошибок те же, что в ответах API. */
export function validateOrder(form: OrderFormState, mode: 'create' | 'edit', t: Translate): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.client) errors.client = t('errors.requiredField')
  if (!DECIMAL.test(form.client_rate.trim())) errors.client_rate = t('errors.invalidNumber')
  for (const key of ['delivery_days', 'payment_delay_days'] as const) {
    if (form[key].trim() && !INT.test(form[key].trim())) errors[key] = t('errors.invalidNumber')
  }
  if (mode === 'create') form.consignments.forEach((c, i) => { validateConsignment(c, `consignments.${String(i)}`, t, errors) })
  return errors
}

const idOrNull = (v: string) => (v ? Number(v) : null)
const intOrNull = (v: string) => (v.trim() ? Number(v.trim()) : null)

export function consignmentPayload(c: ConsignmentForm, tz: string | undefined) {
  const kinds = ['load', 'unload'] as const
  return {
    name: c.name.trim(),
    weight_kg: c.weight_kg.trim(),
    volume_m3: c.volume_m3.trim(),
    pallets: Number(c.pallets.trim() || '0'),
    packaging: idOrNull(c.packaging),
    points: c.points.map((p, i) => ({
      kind: kinds[i],
      window_from: fromInputDateTime(p.window_from, tz),
      window_to: p.window_to ? fromInputDateTime(p.window_to, tz) : null,
      country: idOrNull(p.country),
      city: p.city.trim(),
      street: p.street,
      method: idOrNull(p.method),
      contact: p.contact,
      postal_code: p.postal_code,
      lat: p.lat.trim() || null,
      lng: p.lng.trim() || null,
      note: p.note,
    })),
  }
}

/**
 * Тело заказа. Создание: можно с грузами. Правка (PATCH): без статуса, номера и грузов - сервер их отклоняет.
 * manager/currency не уходят, если селектора нет (нет users.view / handbooks.view): сервер подставит умолчания.
 */
export function orderPayload(form: OrderFormState, mode: 'create' | 'edit', tz: string | undefined, opts: { sendManagers: boolean }) {
  const body: Record<string, unknown> = {
    client: form.client?.id,
    client_ref: form.client_ref.trim(),
    contract_number: form.contract_number.trim(),
    contact: idOrNull(form.contact),
    client_rate: form.client_rate.trim(),
    transport_condition: idOrNull(form.transport_condition),
    delivery_days: intOrNull(form.delivery_days),
    payment_delay_days: intOrNull(form.payment_delay_days),
    payment_delay_condition: idOrNull(form.payment_delay_condition),
    comment: form.comment,
  }
  if (form.currency) body.currency = Number(form.currency)
  if (opts.sendManagers) {
    if (form.manager) body.manager = Number(form.manager)
    body.forwarder = idOrNull(form.forwarder)
    body.extra_managers = form.extra_managers
  }
  if (mode === 'create' && form.consignments.length > 0) {
    body.consignments = form.consignments.map((c) => consignmentPayload(c, tz))
  }
  return body
}

/** Какие пути ошибок сервера есть в форме (остальные уходят в баннер). */
export const ORDER_KNOWN_PATH =
  /^(client|client_ref|contract_number|contact|manager|forwarder|extra_managers|currency|client_rate|transport_condition|delivery_days|payment_delay_days|payment_delay_condition|comment)$|^consignments(\.\d+(\.(name|weight_kg|volume_m3|pallets|packaging|points(\.[01](\.(window_from|window_to|country|city|street|method|contact|postal_code|lat|lng|note))?)?))?)?$/

export const CONSIGNMENT_KNOWN_PATH =
  /^(name|weight_kg|volume_m3|pallets|packaging|points(\.[01](\.(window_from|window_to|country|city|street|method|contact|postal_code|lat|lng|note))?)?)$/
