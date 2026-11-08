import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type {
  EngineInfo, ExpenseRow, FinanceSettings, IncomeRow, LedgerFilters, MigrationData, MigrationIssue, OrderFinance,
  PeriodRow, StatusMappingReport, TripFinance,
} from './ledgerTypes'

const id = (value: number) => String(value)

export const getEngine = (signal?: AbortSignal) => api.get<EngineInfo>('/finance/engine/', undefined, { signal })

const listQuery = (f: LedgerFilters) => ({
  status: f.status || undefined,
  date_from: f.date_from || undefined,
  date_to: f.date_to || undefined,
  needs_review: f.needs_review || undefined,
  page: f.page,
  page_size: f.pageSize,
})

export const listIncomes = (f: LedgerFilters, signal?: AbortSignal) =>
  api.get<Paginated<IncomeRow>>('/finance/incomes/', listQuery(f), { signal })
export const createIncome = (body: { order: number; title: string; category?: string; amount: string }) =>
  api.post<IncomeRow>('/finance/incomes/', body)
export const incomeAction = (incomeId: number, action: 'deliver' | 'confirm' | 'adjust' | 'void', body: Record<string, unknown>) =>
  api.post<IncomeRow>(`/finance/incomes/${id(incomeId)}/${action}/`, body)

export const listExpenses = (f: LedgerFilters, signal?: AbortSignal) =>
  api.get<Paginated<ExpenseRow>>('/finance/expenses/', listQuery(f), { signal })
export const createExpense = (body: Record<string, unknown>) => api.post<ExpenseRow>('/finance/expenses/', body)
export const voidExpense = (expenseId: number, reason: string) =>
  api.post<ExpenseRow>(`/finance/expenses/${id(expenseId)}/void/`, { reason })

export const reallocateExpense = (expenseId: number, method: string) =>
  api.post<ExpenseRow>(`/finance/expenses/${id(expenseId)}/reallocate/`, { method })

export const getOrderFinance = (orderId: number, signal?: AbortSignal) =>
  api.get<OrderFinance>(`/orders/${id(orderId)}/finance/`, undefined, { signal })
export const getTripFinance = (tripId: number, signal?: AbortSignal) =>
  api.get<TripFinance>(`/trips/${id(tripId)}/finance/`, undefined, { signal })
export const createCarrierExpense = (tripId: number) =>
  api.post<unknown>(`/finance/trips/${id(tripId)}/carrier-expense/`, {})

export const getFinanceSettings = (signal?: AbortSignal) => api.get<FinanceSettings>('/finance/settings/', undefined, { signal })
export const patchFinanceSettings = (body: Record<string, unknown>) => api.patch<FinanceSettings>('/finance/settings/', body)
export const getStatusMapping = (signal?: AbortSignal) =>
  api.get<StatusMappingReport>('/finance/settings/status-mapping/', undefined, { signal })
export const mapStatus = (value: number, code: string) =>
  api.post<StatusMappingReport>('/finance/settings/status-mapping/', { value, code })

export const listPeriods = (signal?: AbortSignal) => api.get<PeriodRow[]>('/finance/periods/', undefined, { signal })
export const closePeriod = (year: number, month: number, comment: string) =>
  api.post<PeriodRow>('/finance/periods/', { year, month, comment })
export const reopenPeriod = (periodId: number, reason: string) =>
  api.post<PeriodRow>(`/finance/periods/${id(periodId)}/reopen/`, { reason })

export const getMigration = (signal?: AbortSignal) => api.get<MigrationData>('/finance/migration/', undefined, { signal })
export const resolveIssue = (issueId: number, body: Record<string, unknown>) =>
  api.post<MigrationIssue>(`/finance/migration/issues/${id(issueId)}/resolve/`, body)
