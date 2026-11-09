import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { BlockedPage } from '../../features/errors/BlockedPage'
import { api } from '../api/client'
import { onApiEvent } from '../api/events'
import type { LoginResponse } from '../api/types'
import { AuthContext, type AuthContextValue } from './authContext'
import { platformSessionQuery, sessionQuery } from './sessionQuery'
import { clearTokens, getContext, hasTokens as storedTokens, setTokens, type AuthContextKind } from './tokens'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [hasTokens, setHasTokens] = useState(storedTokens)
  const [blocked, setBlocked] = useState(false)
  const [context, setContext] = useState<AuthContextKind>(getContext)

  useEffect(() => {
    const offLogout = onApiEvent('logout', () => {
      setHasTokens(false)
      queryClient.clear()
    })
    const offBlocked = onApiEvent('blocked', () => {
      setBlocked(true)
      void queryClient.cancelQueries()
    })
    return () => {
      offLogout()
      offBlocked()
    }
  }, [queryClient])

  const logout = useCallback(() => {
    clearTokens()
    setHasTokens(false)
    setBlocked(false)
    queryClient.clear()
    void navigate('/login', { replace: true })
  }, [queryClient, navigate])

  const login = useCallback(
    async (loginValue: string, password: string): Promise<AuthContextKind> => {
      const data = await api.post<LoginResponse>(
        '/auth/login/',
        { login: loginValue, password },
        { auth: false },
      )
      const next: AuthContextKind = data.context === 'platform' ? 'platform' : 'company'
      queryClient.clear()
      setTokens({ access: data.access, refresh: data.refresh, context: next })
      setContext(next)
      setHasTokens(true)
      try {
        if (next === 'platform') await queryClient.query(platformSessionQuery)
        else await queryClient.query(sessionQuery)
      } catch (error) {
        // вход не состоялся целиком: токены не должны остаться
        clearTokens()
        setHasTokens(false)
        queryClient.clear()
        throw error
      }
      return next
    },
    [queryClient],
  )

  const switchCompany = useCallback(
    async (companyId: number) => {
      const data = await api.post<LoginResponse>('/auth/switch-company/', {
        company_id: companyId,
      })
      setTokens({ access: data.access, refresh: data.refresh, context: 'company' })
      setContext('company')
      queryClient.clear() // данные прежней компании не должны остаться в кэше
      await queryClient.query(sessionQuery)
      void navigate('/', { replace: true })
    },
    [queryClient, navigate],
  )

  const switchToPlatform = useCallback(async () => {
    const data = await api.post<LoginResponse>('/auth/switch-company/', { context: 'platform' })
    setTokens({ access: data.access, refresh: data.refresh, context: 'platform' })
    setContext('platform')
    queryClient.clear() // данные компании не должны попасть в платформенный контекст
    await queryClient.query(platformSessionQuery)
    void navigate('/platform', { replace: true })
  }, [queryClient, navigate])

  const value = useMemo<AuthContextValue>(
    () => ({ hasTokens, blocked, context, login, logout, switchCompany, switchToPlatform }),
    [hasTokens, blocked, context, login, logout, switchCompany, switchToPlatform],
  )

  return (
    <AuthContext.Provider value={value}>
      {blocked ? <BlockedPage onLogout={logout} /> : children}
    </AuthContext.Provider>
  )
}
