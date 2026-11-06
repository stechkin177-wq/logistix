import { useQuery } from '@tanstack/react-query'
import { api } from '../../../shared/api/client'
import type { Consignment } from '../../consignments/types'
import type { Paginated } from '../../../shared/ui/Pagination'

/** Поиск грузов по названию для набора грузов рейса (первые 20; запрос по каждому вводу отменяет предыдущий). */
export function useConsignmentListSearch(q: string) {
  return useQuery({
    queryKey: ['consignments', 'picker', q],
    queryFn: ({ signal }) => api.get<Paginated<Consignment>>('/consignments/', { q, page_size: 20 }, { signal }),
    staleTime: 10_000,
  })
}
