import { api, type Query } from '../../shared/api/client'
import type { ComboOption } from '../../shared/ui/Combobox'
import type { Paginated } from '../../shared/ui/Pagination'
import type { BoardColumn, Order, OrderLine, OrderLinePayload, OrderListFilters, OrderListParams, TripRef } from './types'

/** Параметры фильтров как их понимает бэкенд (список, канбан и Excel используют одни и те же). */
export function filterQuery(f: OrderListFilters): Query {
  return {
    q: f.q,
    status: f.status.length ? f.status.join(',') : undefined,
    client: f.client,
    carrier: f.carrier,
    loading_from: f.loading_from,
    loading_to: f.loading_to,
    created_from: f.created_from,
    created_to: f.created_to,
    completed_from: f.completed_from,
    completed_to: f.completed_to,
    unassigned: f.unassigned ? 1 : undefined,
  }
}

export const listOrders = (p: OrderListParams, signal?: AbortSignal) =>
  api.get<Paginated<Order>>('/orders/', { ...filterQuery(p), ordering: p.ordering, page: p.page, page_size: p.pageSize }, { signal })

export const fetchBoard = (f: OrderListFilters, signal?: AbortSignal) =>
  api.get<BoardColumn[]>('/orders/board/', filterQuery(f), { signal })

export const exportOrders = (p: OrderListParams) => api.download('/orders/export/', { ...filterQuery(p), ordering: p.ordering })

export const getOrder = (id: number, signal?: AbortSignal) => api.get<Order>(`/orders/${String(id)}/`, undefined, { signal })

export const createOrder = (body: unknown) => api.post<Order>('/orders/', body)
export const updateOrder = (id: number, body: unknown) => api.patch<Order>(`/orders/${String(id)}/`, body)
export const deleteOrder = (id: number) => api.delete(`/orders/${String(id)}/`)
export const changeOrderStatus = (id: number, status: number) => api.post<Order>(`/orders/${String(id)}/status/`, { status })

export const createConsignment = (body: unknown) => api.post<unknown>('/consignments/', body)
export const updateConsignment = (id: number, body: unknown) => api.patch<unknown>(`/consignments/${String(id)}/`, body)
export const deleteConsignment = (id: number) => api.delete(`/consignments/${String(id)}/`)

export const listOrderLines = (order: number, signal?: AbortSignal) =>
  api.get<Paginated<OrderLine>>('/order-lines/', { order, page_size: 200 }, { signal })
export const createOrderLine = (body: OrderLinePayload) => api.post<OrderLine>('/order-lines/', body)
export const updateOrderLine = (id: number, body: OrderLinePayload) => api.patch<OrderLine>(`/order-lines/${String(id)}/`, body)
export const deleteOrderLine = (id: number) => api.delete(`/order-lines/${String(id)}/`)

/** Рейсы, везущие груз заказа. Фильтра по заказу у API рейсов нет: обычные рейсы находятся по номеру заказа
 * в номере рейса ({order}-{n}), сборные - просмотром сборных рейсов и отбором по составу. */
export async function tripsOfOrder(order: { id: number; number: string }, signal?: AbortSignal): Promise<TripRef[]> {
  const [single, consolidated] = await Promise.all([
    api.get<Paginated<TripRef>>('/trips/', { q: order.number, page_size: 200 }, { signal }),
    api.get<Paginated<TripRef>>('/trips/', { only_consolidated: 1, page_size: 200 }, { signal }),
  ])
  const seen = new Map<number, TripRef>()
  for (const trip of [...single.results, ...consolidated.results]) {
    if (trip.orders.some((o) => o.id === order.id)) seen.set(trip.id, trip)
  }
  return [...seen.values()].sort((a, b) => a.id - b.id)
}

export const orderOption = (o: Order): ComboOption => ({ id: o.id, label: o.number })
