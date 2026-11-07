import { api, type Query } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type {
  DebtsResponse, FinanceSummary, Invoice, InvoiceListFilters, InvoicePayload, OperationsFilters, OperationsResponse,
  Payment, PaymentPayload, PaymentsResponse, Rate, RateFilters, RatePayload, TripExpenseData,
} from './types'

const id = (value: number) => String(value)

export const listRates = (f: RateFilters, signal?: AbortSignal) =>
  api.get<Paginated<Rate>>('/finance/rates/', { currency: f.currency ?? undefined, page: f.page, page_size: f.pageSize }, { signal })
export const createRate = (body: RatePayload) => api.post<Rate>('/finance/rates/', body)
export const updateRate = (rateId: number, body: Partial<RatePayload>) => api.patch<Rate>(`/finance/rates/${id(rateId)}/`, body)
export const deleteRate = (rateId: number) => api.delete(`/finance/rates/${id(rateId)}/`)

export function invoiceQuery(f: InvoiceListFilters): Query {
  return {
    direction: f.direction || undefined,
    status: f.status || undefined,
    client: f.client ?? undefined,
    carrier: f.carrier ?? undefined,
    order: f.order ?? undefined,
    date_from: f.date_from || undefined,
    date_to: f.date_to || undefined,
    search: f.search || undefined,
    page: f.page,
    page_size: f.pageSize,
  }
}

export const listInvoices = (f: InvoiceListFilters, signal?: AbortSignal) =>
  api.get<Paginated<Invoice>>('/finance/invoices/', invoiceQuery(f), { signal })
export const getInvoice = (invoiceId: number, signal?: AbortSignal) =>
  api.get<Invoice>(`/finance/invoices/${id(invoiceId)}/`, undefined, { signal })
export const createInvoice = (body: InvoicePayload) => api.post<Invoice>('/finance/invoices/', body)
export const updateInvoice = (invoiceId: number, body: InvoicePayload) =>
  api.patch<Invoice>(`/finance/invoices/${id(invoiceId)}/`, body)
export const deleteInvoice = (invoiceId: number) => api.delete(`/finance/invoices/${id(invoiceId)}/`)
export const issueInvoice = (invoiceId: number, overrideReason?: string) =>
  api.post<Invoice>(`/finance/invoices/${id(invoiceId)}/issue/`, overrideReason ? { override_reason: overrideReason } : {})
export const cancelInvoice = (invoiceId: number) => api.post<Invoice>(`/finance/invoices/${id(invoiceId)}/cancel/`, {})

export const listInvoicePayments = (invoiceId: number, signal?: AbortSignal) =>
  api.get<Paginated<Payment>>(`/finance/invoices/${id(invoiceId)}/payments/`, { page_size: 200 }, { signal })
export const addPayment = (invoiceId: number, body: PaymentPayload) =>
  api.post<Payment>(`/finance/invoices/${id(invoiceId)}/payments/`, body)
export const listPayments = (page: number, pageSize: number, direction: string, signal?: AbortSignal) =>
  api.get<PaymentsResponse>('/finance/payments/', { page, page_size: pageSize, direction: direction || undefined }, { signal })
export const deletePayment = (paymentId: number) => api.delete(`/finance/payments/${id(paymentId)}/`)

export function operationsQuery(f: OperationsFilters): Query {
  return {
    date_from: f.date_from || undefined,
    date_to: f.date_to || undefined,
    category: f.category || undefined,
    client: f.client ?? undefined,
    order: f.order ?? undefined,
    page: f.page,
    page_size: f.pageSize,
  }
}
export const listOperations = (f: OperationsFilters, signal?: AbortSignal) =>
  api.get<OperationsResponse>('/finance/operations/', operationsQuery(f), { signal })
export const exportOperations = (f: OperationsFilters) => api.download('/finance/operations/export/', operationsQuery(f))

export const listDebts = (kind: 'clients' | 'carriers', signal?: AbortSignal) =>
  api.get<DebtsResponse>(`/finance/debts/${kind}/`, undefined, { signal })
export const exportDebts = (kind: 'clients' | 'carriers') => api.download(`/finance/debts/${kind}/export/`)
export const getFinanceSummary = (signal?: AbortSignal) => api.get<FinanceSummary>('/finance/summary/', undefined, { signal })

export const getTripExpense = (tripId: number, signal?: AbortSignal) =>
  api.get<TripExpenseData>(`/finance/trips/${id(tripId)}/expense-lines/`, undefined, { signal })
export const createTripExpense = (tripId: number, allocations: { order_id: number; amount: string }[]) =>
  api.post<unknown>(`/finance/trips/${id(tripId)}/expense-lines/`, { allocations })
