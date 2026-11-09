import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  changePlan, createPlan, deletePlan, getCatalog, getSubscription, listCompanies, listHistory, listPlans,
  planAction, previewChange, renew, reorderPlans, updatePlan,
} from './api'

export const usePlans = () => useQuery({ queryKey: ['platform', 'plans'], queryFn: ({ signal }) => listPlans(signal) })
export const useCatalog = () => useQuery({ queryKey: ['platform', 'catalog'], queryFn: ({ signal }) => getCatalog(signal), staleTime: 5 * 60_000 })
export const useCompanies = (q: string, page: number, pageSize: number) =>
  useQuery({ queryKey: ['platform', 'companies', q, page, pageSize], queryFn: ({ signal }) => listCompanies(q, page, pageSize, signal), placeholderData: keepPreviousData })
export const useSubscription = (company: number) =>
  useQuery({ queryKey: ['platform', 'subscription', company], queryFn: ({ signal }) => getSubscription(company, signal) })
export const useHistory = (kind: string, key: string, page: number, pageSize: number) =>
  useQuery({ queryKey: ['platform', 'history', kind, key, page, pageSize], queryFn: ({ signal }) => listHistory(kind, key, page, pageSize, signal), placeholderData: keepPreviousData })
export const usePreview = (company: number, plan: string) =>
  useQuery({ queryKey: ['platform', 'preview', company, plan], queryFn: ({ signal }) => previewChange(company, plan, signal), enabled: plan !== '' })

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['platform'] })
}

export function useSavePlan() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ code, body, create }: { code: string; body: Record<string, unknown>; create: boolean }) =>
      create ? createPlan({ code, ...body }) : updatePlan(code, body),
    onSuccess: invalidate,
  })
}
export function usePlanAction() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ code, action }: { code: string; action: Parameters<typeof planAction>[1] }) => planAction(code, action), onSuccess: invalidate })
}
export function useDeletePlan() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (code: string) => deletePlan(code), onSuccess: invalidate })
}
export function useReorder() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (codes: string[]) => reorderPlans(codes), onSuccess: invalidate })
}
export function useChangePlan(company: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ plan, period }: { plan: string; period: 'keep' | 'restart' }) => changePlan(company, plan, period), onSuccess: invalidate })
}
export function useRenew(company: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (periods: number) => renew(company, periods), onSuccess: invalidate })
}
