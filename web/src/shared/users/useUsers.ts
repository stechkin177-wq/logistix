import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useSession } from '../auth/useSession'

export interface CompanyUser {
  /** id членства (адрес /users/{id}/). */
  id: number
  role: number | null
  role_name: string | null
  department: number | null
  /** id пользователя (поля manager/forwarder заказа), а не членства. */
  user_id: number
  full_name: string
  email: string | null
  phone: string | null
  is_active: boolean
}

export const userLabel = (u: CompanyUser): string => u.full_name || u.email || u.phone || `#${String(u.user_id)}`

/** Сотрудники компании (GET /users/ требует users.view; без права запрос не отправляется). */
export function useUsersQuery() {
  const { hasPermission, session } = useSession()
  const allowed = hasPermission('users.view')
  const query = useQuery({
    queryKey: ['users', 'list'],
    queryFn: ({ signal }) => api.get<CompanyUser[]>('/users/', undefined, { signal }),
    enabled: allowed && session !== undefined,
    staleTime: 60_000,
  })
  return { ...query, allowed }
}

export function useUsers() {
  const query = useUsersQuery()
  return { users: query.data ?? [], allowed: query.allowed, isLoading: query.isPending && query.allowed }
}
