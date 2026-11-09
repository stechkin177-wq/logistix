import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../api/errors'
import type { Session, SubscriptionState } from '../api/types'
import { useAuth } from './useAuth'
import { sessionQuery } from './sessionQuery'

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous' | 'error'

export interface UseSession {
  status: SessionStatus
  session: Session | undefined
  error: unknown
  refetch: () => void
  /** Фактический статус подписки (undefined, пока сессия не загружена). */
  subscriptionStatus: SubscriptionState | undefined
  hasPermission: (code: string) => boolean
  hasModule: (module: string) => boolean
}

export function useSession(): UseSession {
  const { hasTokens, blocked, context } = useAuth()
  const query = useQuery({ ...sessionQuery, enabled: hasTokens && !blocked && context === 'company' })
  const session = query.data

  let status: SessionStatus
  if (!hasTokens) status = 'anonymous'
  else if (session) status = 'authenticated'
  else if (query.isError) {
    status = query.error instanceof ApiError && query.error.status === 401 ? 'anonymous' : 'error'
  } else status = 'loading'

  return {
    status,
    session,
    error: query.error,
    refetch: () => void query.refetch(),
    subscriptionStatus: session?.subscription.status,
    hasPermission: (code) => session?.permissions.includes(code) ?? false,
    hasModule: (module) => session?.modules.includes(module) ?? false,
  }
}
