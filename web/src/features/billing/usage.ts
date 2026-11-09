import { useQuery } from '@tanstack/react-query'
import { api } from '../../shared/api/client'

export type LimitState = 'ok' | 'near' | 'reached' | 'exceeded'

export interface UsageRow {
  code: string
  name: string
  unit: string
  scope: 'total' | 'month'
  limit: number | null
  usage: number | null
  enforced: boolean
  exceeded: boolean
  state: LimitState
}

export interface Usage {
  results: UsageRow[]
  warnings: UsageRow[]
}

/** Использование лимитов тарифа компанией (GET /billing/usage/). */
export function useUsage(enabled = true) {
  return useQuery({
    queryKey: ['billing', 'usage'],
    queryFn: ({ signal }) => api.get<Usage>('/billing/usage/', undefined, { signal }),
    enabled,
    staleTime: 60_000,
  })
}
