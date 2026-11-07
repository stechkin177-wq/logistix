import type { HandbookValue } from '../shared/api/types'
import type { BoardColumn, Order, OrderConsignment, OrderLine } from '../features/orders/types'

export function hv(handbook: string, id: number, name: string, extra: Partial<HandbookValue> = {}): HandbookValue {
  return { id, handbook, name, code: '', order: id, is_initial: false, is_final: false, is_active: true, is_system: false, ...extra }
}

export const ORDER_STATUSES = [
  hv('order_status', 1, 'Новый', { is_initial: true }),
  hv('order_status', 2, 'В работе'),
  hv('order_status', 6, 'Завершён', { code: 'completed', is_final: true }),
]

export const handbookBody = (code: string, values: HandbookValue[]) => ({ code, name: code, group: 'g', values })

export const CURRENCIES = [hv('currency', 11, 'Тенге', { code: 'KZT' }), hv('currency', 12, 'Доллар США', { code: 'USD' })]

export function makeConsignment(over: Partial<OrderConsignment> = {}): OrderConsignment {
  return {
    id: 31, name: 'Станки', weight_kg: '1200.00', volume_m3: '8.50', pallets: 4, packaging: null, packaging_name: null,
    status: 90, status_name: 'Принят', created_at: '2026-10-30T05:00:00Z',
    points: [
      { id: 1, kind: 'load', window_from: '2026-11-05T04:00:00Z', window_to: null, country: null, country_name: null, city: 'Алматы', street: '', method: null, method_name: null, contact: '', postal_code: '', lat: null, lng: null, note: '' },
      { id: 2, kind: 'unload', window_from: '2026-11-08T04:00:00Z', window_to: null, country: null, country_name: null, city: 'Астана', street: '', method: null, method_name: null, contact: '', postal_code: '', lat: null, lng: null, note: '' },
    ],
    ...over,
  }
}

export function makeOrder(over: Partial<Order> = {}): Order {
  return {
    id: 5, number: 'ORD-2026-00005', client: 7, client_name: 'ТОО Ромашка', client_ref: '', contract_number: 'Д-1', contact: null,
    manager: 1, manager_name: 'Админ Админов', forwarder: null, extra_managers: [], legal_entity: 3, client_rate: '250000.00',
    currency: 11, transport_condition: null, delivery_days: 5, payment_delay_days: null, payment_delay_condition: null, comment: '',
    status: 1, status_name: 'Новый', completed_at: null, route: 'Алматы → Астана', has_carrier: false,
    revenue: '250000.00', cost: '100000.00', profit: '150000.00', margin_pct: '60.00',
    consignments: [makeConsignment()],
    history: [{ id: 1, from_status: null, from_status_name: null, to_status: 1, to_status_name: 'Новый', user: 1, created_at: '2026-10-30T05:00:00Z' }],
    created_by: 1, created_at: '2026-10-30T05:00:00Z', updated_at: '2026-10-30T05:00:00Z',
    ...over,
  }
}

export function makeLine(over: Partial<OrderLine> = {}): OrderLine {
  return {
    id: 100, order: 5, order_number: 'ORD-2026-00005', title: 'Начальная ставка', category: '', income: '250000.00', expense: '0.00',
    date: '2026-10-30', is_base: true, created_at: '2026-10-30T05:00:00Z', updated_at: '2026-10-30T05:00:00Z', ...over,
  }
}

export const BOARD: BoardColumn[] = [
  { status: { id: 1, name: 'Новый' }, count: 120, has_more: true, orders: [
    { id: 5, number: 'ORD-2026-00005', client: 'ТОО Ромашка', route: 'Алматы → Астана', carriers: [], rate: '250000.00', currency: 'KZT', loading_at: '2026-11-05T04:00:00+00:00', has_carrier: false },
    { id: 6, number: 'ORD-2026-00006', client: 'ИП Лютик', route: '', carriers: ['ИП Быстров'], rate: '10.00', currency: 'USD', loading_at: null, has_carrier: true },
  ] },
  { status: { id: 2, name: 'В работе' }, count: 0, has_more: false, orders: [] },
  { status: { id: 6, name: 'Завершён' }, count: 0, has_more: false, orders: [] },
]
