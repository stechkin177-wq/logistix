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
    label: f.label,
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

const LINES_PAGE_SIZE = 200
const LINES_MAX_PAGES = 20

/** Все строки заказа: страницы подгружаются по `next` (не больше LINES_MAX_PAGES), итоги на странице не расходятся с таблицей. */
export async function listOrderLines(order: number, signal?: AbortSignal): Promise<Paginated<OrderLine>> {
  const results: OrderLine[] = []
  let count = 0
  for (let page = 1; page <= LINES_MAX_PAGES; page++) {
    const part = await api.get<Paginated<OrderLine>>('/order-lines/', { order, page_size: LINES_PAGE_SIZE, page }, { signal })
    results.push(...part.results)
    count = part.count
    if (!part.next) break
  }
  return { count, next: null, previous: null, results }
}
export const createOrderLine = (body: OrderLinePayload) => api.post<OrderLine>('/order-lines/', body)
export const updateOrderLine = (id: number, body: OrderLinePayload) => api.patch<OrderLine>(`/order-lines/${String(id)}/`, body)
export const deleteOrderLine = (id: number) => api.delete(`/order-lines/${String(id)}/`)

/** Рейсы, везущие груз заказа: GET /trips/?order=<id> (одиночные и сборные, без дублей). */
export async function tripsOfOrder(order: { id: number }, signal?: AbortSignal): Promise<TripRef[]> {
  const result = await api.get<Paginated<TripRef>>('/trips/', { order: order.id, page_size: 200 }, { signal })
  return result.results
}

export const orderOption = (o: Order): ComboOption => ({ id: o.id, label: o.number })
