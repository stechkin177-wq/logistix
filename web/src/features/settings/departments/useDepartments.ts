import { useQuery } from '@tanstack/react-query'
import { api } from '../../../shared/api/client'
import { useSession } from '../../../shared/auth/useSession'

export interface Department {
  id: number
  name: string
}

/** Отделы компании (раздел прав users). */
export function useDepartments() {
  const { hasPermission } = useSession()
  const allowed = hasPermission('users.view')
  const query = useQuery({
    queryKey: ['departments', 'list'],
    queryFn: ({ signal }) => api.get<Department[]>('/departments/', undefined, { signal }),
    enabled: allowed,
  })
  return { ...query, departments: query.data ?? [] }
}
