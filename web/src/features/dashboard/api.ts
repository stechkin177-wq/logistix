import { api, type Query } from '../../shared/api/client'
import type { DashboardSummary } from '../../shared/api/types'

export const fetchSummary = (query?: Query, signal?: AbortSignal) =>
  api.get<DashboardSummary>('/dashboard/summary/', query, { signal })
