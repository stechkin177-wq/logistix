import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '../../shared/auth/useSession'
import {
  closePeriod, createCarrierExpense, createExpense, createIncome, getEngine, getFinanceSettings, getMigration,
  getOrderFinance, getStatusMapping, getTripFinance, incomeAction, listExpenses, listIncomes, listPeriods,
  mapStatus, patchFinanceSettings, reopenPeriod, resolveIssue, voidExpense,
} from './ledgerApi'
import type { LedgerFilters } from './ledgerTypes'

function useInvalidate() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['finance'] }),
      qc.invalidateQueries({ queryKey: ['orders'] }),
      qc.invalidateQueries({ queryKey: ['trips'] }),
      qc.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
}

/** Режим учёта компании; запрос только при праве finance.view. Пока не известен - 'legacy'. */
export function useFinanceEngine() {
  const { hasPermission, hasModule, session } = useSession()
  const query = useQuery({
    queryKey: ['finance', 'engine'],
    queryFn: ({ signal }) => getEngine(signal),
    enabled: session !== undefined && hasModule('finance') && hasPermission('finance.view'),
    staleTime: 60_000,
  })
  return { engine: query.data?.engine ?? 'legacy', frozen: query.data?.financial_writes_frozen ?? false, isLoading: query.isPending }
}

export function useIncomes(filters: LedgerFilters) {
  return useQuery({
    queryKey: ['finance', 'incomes', filters],
    queryFn: ({ signal }) => listIncomes(filters, signal),
    placeholderData: keepPreviousData,
  })
}

export function useExpenses(filters: LedgerFilters) {
  return useQuery({
    queryKey: ['finance', 'expenses', filters],
    queryFn: ({ signal }) => listExpenses(filters, signal),
    placeholderData: keepPreviousData,
  })
}

export function useCreateIncome() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: createIncome, onSuccess: invalidate })
}

export function useIncomeAction() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, action, body }: { id: number; action: 'deliver' | 'confirm' | 'adjust' | 'void'; body: Record<string, unknown> }) =>
      incomeAction(id, action, body),
    onSuccess: invalidate,
  })
}

export function useCreateExpense() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: createExpense, onSuccess: invalidate })
}

export function useVoidExpense() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, reason }: { id: number; reason: string }) => voidExpense(id, reason), onSuccess: invalidate })
}

export function useOrderFinance(orderId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['finance', 'order-card', orderId],
    queryFn: ({ signal }) => getOrderFinance(orderId ?? 0, signal),
    enabled: enabled && orderId !== null,
  })
}

export function useTripFinance(tripId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['finance', 'trip-card', tripId],
    queryFn: ({ signal }) => getTripFinance(tripId ?? 0, signal),
    enabled: enabled && tripId !== null,
  })
}

export function useCreateCarrierExpense() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (tripId: number) => createCarrierExpense(tripId), onSuccess: invalidate })
}

export function useFinanceSettings() {
  return useQuery({ queryKey: ['finance', 'settings'], queryFn: ({ signal }) => getFinanceSettings(signal) })
}

export function usePatchFinanceSettings() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: patchFinanceSettings, onSuccess: invalidate })
}

export function useStatusMapping() {
  return useQuery({ queryKey: ['finance', 'status-mapping'], queryFn: ({ signal }) => getStatusMapping(signal) })
}

export function useMapStatus() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ value, code }: { value: number; code: string }) => mapStatus(value, code), onSuccess: invalidate })
}

export function usePeriods() {
  return useQuery({ queryKey: ['finance', 'periods'], queryFn: ({ signal }) => listPeriods(signal) })
}

export function useClosePeriod() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ year, month, comment }: { year: number; month: number; comment: string }) => closePeriod(year, month, comment),
    onSuccess: invalidate,
  })
}

export function useReopenPeriod() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, reason }: { id: number; reason: string }) => reopenPeriod(id, reason), onSuccess: invalidate })
}

export function useMigration() {
  return useQuery({ queryKey: ['finance', 'migration'], queryFn: ({ signal }) => getMigration(signal) })
}

export function useResolveIssue() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => resolveIssue(id, body), onSuccess: invalidate })
}
