import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { BlockedPage } from '../../features/errors/BlockedPage'
import { api } from '../api/client'
import { onApiEvent } from '../api/events'
import type { LoginResponse, TotpChallenge } from '../api/types'
import { AuthContext, type AuthContextValue, type LoginResult } from './authContext'
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
    // сервер отзывает выданные токены (все устройства); ответ не ждём, ошибка выходу не мешает
    if (storedTokens()) void api.post('/auth/logout/').catch(() => undefined)
    clearTokens()
    setHasTokens(false)
    setBlocked(false)
    queryClient.clear()
    void navigate('/login', { replace: true })
  }, [queryClient, navigate])

  /** Принять токены входа (после пароля или после кода TOTP) и загрузить сессию контекста. */
  const finishLogin = useCallback(
    async (data: LoginResponse): Promise<AuthContextKind> => {
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

  const login = useCallback(
    async (loginValue: string, password: string): Promise<LoginResult> => {
      const data = await api.post<LoginResponse | TotpChallenge>(
        '/auth/login/',
        { login: loginValue, password },
        { auth: false },
      )
      if ('challenge' in data) return { kind: 'totp', challenge: data.challenge, setup: data.totp_setup_required }
      return { kind: 'done', context: await finishLogin(data) }
    },
    [finishLogin],
  )

  const completeTotp = useCallback(
    async (challenge: string, code: string) => {
      const data = await api.post<LoginResponse>('/auth/totp/', { challenge, code }, { auth: false })
      return finishLogin(data)
    },
    [finishLogin],
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

  const switchToPlatform = useCallback(async (code?: string) => {
    const data = await api.post<LoginResponse>('/auth/switch-company/', { context: 'platform', ...(code ? { code } : {}) })
    setTokens({ access: data.access, refresh: data.refresh, context: 'platform' })
    setContext('platform')
    queryClient.clear() // данные компании не должны попасть в платформенный контекст
    await queryClient.query(platformSessionQuery)
    void navigate('/platform', { replace: true })
  }, [queryClient, navigate])

  const value = useMemo<AuthContextValue>(
    () => ({ hasTokens, blocked, context, login, completeTotp, logout, switchCompany, switchToPlatform }),
    [hasTokens, blocked, context, login, completeTotp, logout, switchCompany, switchToPlatform],
  )

  return (
    <AuthContext.Provider value={value}>
      {blocked ? <BlockedPage onLogout={logout} /> : children}
    </AuthContext.Provider>
  )
}
