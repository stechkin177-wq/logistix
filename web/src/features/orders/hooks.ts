import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '../../shared/auth/useSession'
import { useHandbookValues } from '../../shared/handbooks/useHandbook'
import { getParty } from '../parties/api'
import type { ComboOption } from '../../shared/ui/Combobox'
import {
  changeOrderStatus, createConsignment, createOrder, createOrderLine, deleteConsignment, deleteOrder,
  deleteOrderLine, fetchBoard, getOrder, listOrderLines, listOrders, tripsOfOrder, updateConsignment, updateOrder,
  updateOrderLine,
} from './api'
import type { Order, OrderLinePayload, OrderListFilters, OrderListParams } from './types'
import { useDashboardSummary } from '../dashboard/hooks'

export function useOrderList(params: OrderListParams) {
  return useQuery({
    queryKey: ['orders', 'list', params],
    queryFn: ({ signal }) => listOrders(params, signal),
    placeholderData: keepPreviousData,
  })
}

export function useOrderBoard(filters: OrderListFilters, enabled: boolean) {
  return useQuery({
    queryKey: ['orders', 'board', filters],
    queryFn: ({ signal }) => fetchBoard(filters, signal),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useOrder(id: number | null) {
  return useQuery({
    queryKey: ['orders', 'detail', id],
    queryFn: ({ signal }) => getOrder(id ?? 0, signal),
    enabled: id !== null,
  })
}

/** Все изменения заказа (в т.ч. грузов и строк) обновляют списки, канбан, карточку и сводку. */
function useInvalidateOrders() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['orders'] }),
      qc.invalidateQueries({ queryKey: ['dashboard'] }),
      qc.invalidateQueries({ queryKey: ['consignments'] }),
    ])
}

export function useChangeOrderStatus() {
  const invalidate = useInvalidateOrders()
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: number }) => changeOrderStatus(id, status),
    onSuccess: invalidate,
  })
}

export function useCreateOrder() {
  const invalidate = useInvalidateOrders()
  return useMutation({ mutationFn: (body: unknown) => createOrder(body), onSuccess: invalidate })
}

export function useUpdateOrder(id: number) {
  const invalidate = useInvalidateOrders()
  return useMutation({ mutationFn: (body: unknown) => updateOrder(id, body), onSuccess: invalidate })
}

export function useDeleteOrder() {
  const invalidate = useInvalidateOrders()
  return useMutation({ mutationFn: (id: number) => deleteOrder(id), onSuccess: invalidate })
}

export function useSaveConsignment() {
  const invalidate = useInvalidateOrders()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: unknown }) =>
      id === null ? createConsignment(body) : updateConsignment(id, body),
    onSuccess: invalidate,
  })
}

export function useDeleteConsignment() {
  const invalidate = useInvalidateOrders()
  return useMutation({ mutationFn: (id: number) => deleteConsignment(id), onSuccess: invalidate })
}

export function useOrderLines(order: number, enabled: boolean) {
  return useQuery({
    queryKey: ['orders', 'lines', order],
    queryFn: ({ signal }) => listOrderLines(order, signal),
    enabled,
  })
}

export function useSaveOrderLine() {
  const invalidate = useInvalidateOrders()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: OrderLinePayload }) =>
      id === null ? createOrderLine(body) : updateOrderLine(id, body),
    onSuccess: invalidate,
  })
}

export function useDeleteOrderLine() {
  const invalidate = useInvalidateOrders()
  return useMutation({ mutationFn: (id: number) => deleteOrderLine(id), onSuccess: invalidate })
}

export function useTripsOfOrder(order: Pick<Order, 'id' | 'number'>, enabled: boolean) {
  return useQuery({
    queryKey: ['trips', 'of-order', order.id],
    queryFn: ({ signal }) => tripsOfOrder(order, signal),
    enabled,
  })
}

/** Статусы заказа: из справочника (handbooks.view), иначе - из сводки дашборда (orders.view). */
export function useOrderStatuses() {
  const { hasPermission } = useSession()
  const handbook = useHandbookValues('order_status')
  const canHandbooks = hasPermission('handbooks.view')
  const summary = useDashboardSummary(!canHandbooks)
  if (canHandbooks) {
    return { statuses: handbook.values.map((v) => ({ id: v.id, name: v.name, code: v.code, isActive: v.is_active })), isLoading: handbook.isLoading }
  }
  return {
    statuses: (summary.data?.orders_by_status ?? []).map((s) => ({ id: s.status_id, name: s.status, code: '', isActive: true })),
    isLoading: summary.isPending,
  }
}

/** Валюты: id -> код (handbooks.view); без права - пусто. */
export function useCurrencies() {
  const { values } = useHandbookValues('currency')
  return { currencies: values, codeOf: (id: number | null | undefined) => values.find((v) => v.id === id)?.code ?? '' }
}

/** Подпись выбранного клиента/перевозчика по id из адреса (для Combobox фильтра). */
export function usePartyOption(kind: 'clients' | 'carriers', id: number | null): ComboOption | null {
  const query = useQuery({
    queryKey: [kind, 'detail', id],
    queryFn: ({ signal }) => getParty(kind, id ?? 0, signal),
    enabled: id !== null,
    staleTime: 5 * 60_000,
  })
  if (id === null) return null
  return { id, label: query.data?.name ?? `#${String(id)}` }
}
