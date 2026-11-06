import { useQuery } from '@tanstack/react-query'
import { fetchSummary } from './api'

export const SUMMARY_KEY = ['dashboard', 'summary'] as const

export function useDashboardSummary(enabled = true) {
  return useQuery({ queryKey: SUMMARY_KEY, queryFn: ({ signal }) => fetchSummary(signal), enabled })
}
