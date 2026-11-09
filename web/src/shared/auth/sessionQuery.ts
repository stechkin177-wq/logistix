import { api } from '../api/client'
import type { PlatformSession, Session } from '../api/types'

export const SESSION_KEY = ['session'] as const

export const sessionQuery = {
  queryKey: SESSION_KEY,
  queryFn: () => api.get<Session>('/session/'),
  staleTime: 60_000,
} as const

export const PLATFORM_SESSION_KEY = ['platform-session'] as const

export const platformSessionQuery = {
  queryKey: PLATFORM_SESSION_KEY,
  queryFn: () => api.get<PlatformSession>('/platform/session/'),
  staleTime: 60_000,
} as const
