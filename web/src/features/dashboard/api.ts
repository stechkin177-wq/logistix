import { api } from '../../shared/api/client'
import type { DashboardSummary } from '../../shared/api/types'

export const fetchSummary = (signal?: AbortSignal) =>
  api.get<DashboardSummary>('/dashboard/summary/', undefined, { signal })
