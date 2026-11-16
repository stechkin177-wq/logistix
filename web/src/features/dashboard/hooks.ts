import { useQuery } from '@tanstack/react-query'
import type { Query } from '../../shared/api/client'
import { fetchSummary } from './api'

export const SUMMARY_KEY = ['dashboard', 'summary'] as const

/** query - необязательный период прибыли (profit_from/profit_to); без него - текущий месяц. */
export function useDashboardSummary(enabled = true, query?: Query) {
  return useQuery({ queryKey: [...SUMMARY_KEY, query ?? null], queryFn: ({ signal }) => fetchSummary(query, signal), enabled })
}
