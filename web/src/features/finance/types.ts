/** Типы ответов /api/finance/* (суммы - строки Decimal, как их отдаёт бэкенд). */
import type { ExcludedBase } from '../../shared/api/types'

export interface CurrencyRef {
  id: number
  code: string
  name: string
}

export interface Rate {
  id: number
  currency: CurrencyRef
  date: string
  rate: string
  created_at: string
}

export interface RatePayload {
  currency: number
  date: string
  rate: string
}

export interface RateFilters {
  currency: number | null
  page: number
  pageSize: number
}

export type InvoiceDirection = 'out' | 'in'
export type InvoiceStatus = 'draft' | 'issued' | 'partial' | 'paid' | 'overdue' | 'cancelled'

export interface InvoiceItem {
  id: number
  title: string
  amount_net: string
  line: number | null
}

export interface Invoice {
  id: number
  direction: InvoiceDirection
  number: string
  external_number: string
  status: 'draft' | 'issued' | 'cancelled'
  display_status: InvoiceStatus
  client: { id: number; name: string } | null
  carrier: { id: number; name: string } | null
  order: { id: number; number: string } | null
  trip: { id: number; number: string } | null
  currency: CurrencyRef
  vat_rate: { id: number; code: string; name: string }
  issue_date: string | null
  due_date: string | null
  rate_to_kzt: string | null
  totals: { net: string; vat: string; gross: string }
  paid: string
  balance: string
  comment: string
  items: InvoiceItem[]
  created_at: string
}

export interface InvoiceListFilters {
  direction: InvoiceDirection | ''
  status: InvoiceStatus | ''
  client: number | null
  carrier: number | null
  order: number | null
  date_from: string
  date_to: string
  search: string
  page: number
  pageSize: number
}

export interface InvoiceItemPayload {
  title: string
  amount_net: string
  line: number
}

export interface InvoicePayload {
  direction?: InvoiceDirection
  party?: number
  order?: number | null
  trip?: number | null
  currency?: number
  vat_rate?: number
  due_date?: string | null
  external_number?: string
  comment?: string
  items?: InvoiceItemPayload[]
}

export type PaymentMethod = 'bank' | 'cash' | 'other'

export interface Payment {
  id: number
  invoice: { id: number; number: string; direction: InvoiceDirection }
  date: string
  amount: string
  rate_to_kzt: string
  method: PaymentMethod
  payment_ref: string
  comment: string
  fx_difference_kzt: string
  created_at: string
}

export interface PaymentPayload {
  date: string
  amount: string
  method: PaymentMethod
  payment_ref?: string
  comment?: string
}

export interface OperationRow {
  id: number
  date: string
  order: { id: number; number: string }
  client: { id: number; name: string }
  title: string
  category: string
  income: string
  expense: string
  currency: string
  is_base: boolean
  /** Новая модель: current / prior_base (прежняя база) / no_rate; null в прежнем учёте. */
  base_status?: 'current' | 'prior_base' | 'no_rate' | null
}

export interface OperationsSummary {
  /** Валюта итогов (базовая валюта компании в новой модели, иначе KZT). Поля *_kzt - прежние имена. */
  currency?: string
  excluded?: ExcludedBase | null
  is_partial?: boolean
  income_kzt: string
  expense_kzt: string
  diff_kzt: string
  by_currency: Record<string, { income: string; expense: string; diff: string }>
  unconverted: number
}

export interface OperationsResponse {
  count: number
  next: string | null
  previous: string | null
  results: OperationRow[]
  summary: OperationsSummary
}

export interface OperationsFilters {
  date_from: string
  date_to: string
  category: string
  client: number | null
  order: number | null
  page: number
  pageSize: number
}

export interface DebtRow {
  id: number
  name: string
  issued_kzt: string
  paid_kzt: string
  balance_kzt: string
  overdue_kzt: string
  by_currency: Record<string, { issued: string; paid: string; balance: string }>
  credit_limit?: string
  limit_usage_pct?: string | null
}

export interface FinanceSummary {
  /** Валюта итога месяца; долги и курсовая разница - в debts_currency (KZT). */
  currency: string
  debts_currency?: string
  excluded?: ExcludedBase | null
  is_partial?: boolean
  client_debt_kzt: string
  overdue_kzt: string
  payable_kzt: string
  month_profit_kzt: string
  month_margin_pct: string | null
  fx_difference_kzt: string
  unconverted: number
}

export interface TripExpenseData {
  trip: { id: number; number: string; carrier_price: string; /** Устаревший алиас carrier_price. */ price: string }
  orders: { order_id: number; order_number: string; lines: { id: number; title: string; expense: string }[] }[]
  suggestion: { order_id: number; amount: string }[]
}
