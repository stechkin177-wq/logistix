import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { AdminPlan, Catalog, ChangePreview, HistoryRow, PlatformCompany, SubscriptionInfo } from './types'

export const listPlans = (signal?: AbortSignal) => api.get<AdminPlan[]>('/platform/plans/', undefined, { signal })
export const getCatalog = (signal?: AbortSignal) => api.get<Catalog>('/platform/catalog/', undefined, { signal })
export const createPlan = (body: Record<string, unknown>) => api.post<AdminPlan>('/platform/plans/', body)
export const updatePlan = (code: string, body: Record<string, unknown>) => api.patch<AdminPlan>(`/platform/plans/${code}/`, body)
export const deletePlan = (code: string) => api.delete(`/platform/plans/${code}/`)
export const planAction = (code: string, action: 'publish' | 'unpublish' | 'archive' | 'restore' | 'set-default') =>
  api.post<AdminPlan>(`/platform/plans/${code}/${action}/`, {})
export const reorderPlans = (codes: string[]) => api.post<AdminPlan[]>('/platform/plans/reorder/', { codes })

export const listCompanies = (q: string, page: number, pageSize: number, signal?: AbortSignal) =>
  api.get<Paginated<PlatformCompany>>('/platform/companies/', { q, page, page_size: pageSize }, { signal })
export const getSubscription = (company: number, signal?: AbortSignal) =>
  api.get<SubscriptionInfo>(`/platform/subscriptions/${String(company)}/`, undefined, { signal })
export const previewChange = (company: number, plan: string, signal?: AbortSignal) =>
  api.get<ChangePreview>(`/platform/subscriptions/${String(company)}/change-plan/preview/`, { plan }, { signal })
export const changePlan = (company: number, plan: string, period: 'keep' | 'restart') =>
  api.post<SubscriptionInfo>(`/platform/subscriptions/${String(company)}/change-plan/`, { plan, period })
export const renew = (company: number, periods: number) =>
  api.post<SubscriptionInfo>(`/platform/subscriptions/${String(company)}/renew/`, { periods })

export const listHistory = (kind: string, key: string, page: number, pageSize: number, signal?: AbortSignal) =>
  api.get<Paginated<HistoryRow>>('/platform/history/', { kind, key, page, page_size: pageSize }, { signal })
