import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../api/errors'
import type { PlatformSession } from '../api/types'
import { platformSessionQuery } from './sessionQuery'
import { useAuth } from './useAuth'

export type PlatformSessionStatus = 'loading' | 'authenticated' | 'anonymous' | 'error'

export function usePlatformSession() {
  const { hasTokens, blocked, context } = useAuth()
  const query = useQuery({ ...platformSessionQuery, enabled: hasTokens && !blocked && context === 'platform' })
  const session: PlatformSession | undefined = query.data
  let status: PlatformSessionStatus
  if (!hasTokens) status = 'anonymous'
  else if (session) status = 'authenticated'
  else if (query.isError) {
    status = query.error instanceof ApiError && query.error.status === 401 ? 'anonymous' : 'error'
  } else status = 'loading'
  return {
    status,
    session,
    refetch: () => void query.refetch(),
    can: (permission: string) => session?.permissions.includes(permission) ?? false,
  }
}
