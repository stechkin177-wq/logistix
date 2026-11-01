import { api } from '../api/client'
import type { Session } from '../api/types'

export const SESSION_KEY = ['session'] as const

export const sessionQuery = {
  queryKey: SESSION_KEY,
  queryFn: () => api.get<Session>('/session/'),
  staleTime: 60_000,
} as const
