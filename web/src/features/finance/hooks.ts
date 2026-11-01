import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addPayment, cancelInvoice, createInvoice, createRate, createTripExpense, deleteInvoice, deletePayment, deleteRate,
  getFinanceSummary, getInvoice, getTripExpense, issueInvoice, listDebts, listInvoicePayments, listInvoices,
  listOperations, listPayments, listRates, updateInvoice, updateRate,
} from './api'
import type { InvoiceListFilters, InvoicePayload, OperationsFilters, PaymentPayload, RateFilters, RatePayload } from './types'

/** Любое изменение финансов обновляет счета, оплаты, долги, операции, сводку и заказы (блок «Счета и оплаты»). */
function useInvalidateFinance() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['finance'] }),
      qc.invalidateQueries({ queryKey: ['orders'] }),
      qc.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
}

export function useRates(filters: RateFilters) {
  return useQuery({
    queryKey: ['finance', 'rates', filters],
    queryFn: ({ signal }) => listRates(filters, signal),
    placeholderData: keepPreviousData,
  })
}

export function useSaveRate() {
  const invalidate = useInvalidateFinance()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: RatePayload }) => (id === null ? createRate(body) : updateRate(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteRate() {
  const invalidate = useInvalidateFinance()
  return useMutation({ mutationFn: (id: number) => deleteRate(id), onSuccess: invalidate })
}

export function useInvoices(filters: InvoiceListFilters, enabled = true) {
  return useQuery({
    queryKey: ['finance', 'invoices', 'list', filters],
    queryFn: ({ signal }) => listInvoices(filters, signal),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useInvoice(id: number | null) {
  return useQuery({
    queryKey: ['finance', 'invoices', 'detail', id],
    queryFn: ({ signal }) => getInvoice(id ?? 0, signal),
    enabled: id !== null,
  })
}

export function useSaveInvoice() {
  const invalidate = useInvalidateFinance()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: InvoicePayload }) => (id === null ? createInvoice(body) : updateInvoice(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteInvoice() {
  const invalidate = useInvalidateFinance()
  return useMutation({ mutationFn: (id: number) => deleteInvoice(id), onSuccess: invalidate })
}

export function useIssueInvoice() {
  const invalidate = useInvalidateFinance()
  return useMutation({
    mutationFn: ({ id, overrideReason }: { id: number; overrideReason?: string }) => issueInvoice(id, overrideReason),
    onSuccess: invalidate,
  })
}

export function useCancelInvoice() {
  const invalidate = useInvalidateFinance()
  return useMutation({ mutationFn: (id: number) => cancelInvoice(id), onSuccess: invalidate })
}

export function useInvoicePayments(invoiceId: number | null) {
  return useQuery({
    queryKey: ['finance', 'invoices', 'payments', invoiceId],
    queryFn: ({ signal }) => listInvoicePayments(invoiceId ?? 0, signal),
    enabled: invoiceId !== null,
  })
}

export function useAddPayment() {
  const invalidate = useInvalidateFinance()
  return useMutation({
    mutationFn: ({ invoiceId, body }: { invoiceId: number; body: PaymentPayload }) => addPayment(invoiceId, body),
    onSuccess: invalidate,
  })
}

export function usePayments(page: number, pageSize: number, direction: string) {
  return useQuery({
    queryKey: ['finance', 'payments', page, pageSize, direction],
    queryFn: ({ signal }) => listPayments(page, pageSize, direction, signal),
    placeholderData: keepPreviousData,
  })
}

export function useDeletePayment() {
  const invalidate = useInvalidateFinance()
  return useMutation({ mutationFn: (id: number) => deletePayment(id), onSuccess: invalidate })
}

export function useOperations(filters: OperationsFilters) {
  return useQuery({
    queryKey: ['finance', 'operations', filters],
    queryFn: ({ signal }) => listOperations(filters, signal),
    placeholderData: keepPreviousData,
  })
}

export function useDebts(kind: 'clients' | 'carriers') {
  return useQuery({ queryKey: ['finance', 'debts', kind], queryFn: ({ signal }) => listDebts(kind, signal) })
}

export function useFinanceSummary(enabled = true) {
  return useQuery({ queryKey: ['finance', 'summary'], queryFn: ({ signal }) => getFinanceSummary(signal), enabled })
}

export function useTripExpense(tripId: number | null) {
  return useQuery({
    queryKey: ['finance', 'trip-expense', tripId],
    queryFn: ({ signal }) => getTripExpense(tripId ?? 0, signal),
    enabled: tripId !== null,
  })
}

export function useCreateTripExpense() {
  const invalidate = useInvalidateFinance()
  return useMutation({
    mutationFn: ({ tripId, allocations }: { tripId: number; allocations: { order_id: number; amount: string }[] }) =>
      createTripExpense(tripId, allocations),
    onSuccess: invalidate,
  })
}
