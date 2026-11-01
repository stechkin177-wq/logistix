import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { HandbookDetail, HandbookValue } from '../api/types'
import { useSession } from '../auth/useSession'

/**
 * Значения справочника (GET /handbooks/?code=X). Требует handbooks.view: без права запрос не
 * отправляется, значения пусты (экран деградирует, а не падает).
 */
export function useHandbookValues(code: string, opts: { activeOnly?: boolean } = {}) {
  const { hasPermission, session } = useSession()
  const allowed = hasPermission('handbooks.view')
  const query = useQuery({
    queryKey: ['handbooks', code],
    queryFn: ({ signal }) => api.get<HandbookDetail>('/handbooks/', { code }, { signal }),
    enabled: allowed && session !== undefined,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  })
  const all: HandbookValue[] = query.data?.values ?? []
  const values = opts.activeOnly ? all.filter((v) => v.is_active) : all
  return { values, all, isLoading: query.isPending && allowed, isError: query.isError, allowed }
}

/** Значения для select: активные + (при редактировании) текущее, даже если оно уже отключено. */
export function selectableValues(all: HandbookValue[], currentId: number | null | undefined): HandbookValue[] {
  return all.filter((v) => v.is_active || v.id === currentId)
}
