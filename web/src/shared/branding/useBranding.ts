import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from '../api/client'
import { ApiError } from '../api/errors'
import type { Branding } from '../api/types'
import { useSession } from '../auth/useSession'
import { DEFAULT_BRANDING, applyBranding, sanitizeBranding } from './applyBranding'

function publicBranding(): Promise<Branding> {
  return api.get<Branding>('/branding/', { host: window.location.hostname }, { auth: false })
}

/** До входа - публичное оформление по домену; после входа - оформление компании. */
export function useBranding(): Branding {
  const { status } = useSession()
  const authed = status === 'authenticated'
  const query = useQuery({
    queryKey: ['branding', authed ? 'company' : 'public'],
    queryFn: async () => {
      if (!authed) return publicBranding()
      try {
        return await api.get<Branding>('/company/branding/')
      } catch (error) {
        // чтение оформления требует company.view; без права берём публичное оформление домена
        if (error instanceof ApiError && error.status === 403 && error.code !== 'subscription_blocked') {
          return publicBranding()
        }
        throw error
      }
    },
    enabled: status === 'authenticated' || status === 'anonymous',
    staleTime: 5 * 60_000,
    retry: false,
  })
  return query.data ? sanitizeBranding(query.data) : DEFAULT_BRANDING
}

/** Применяет оформление к документу: один раз на приложение (в провайдерах). */
export function BrandingEffect(): null {
  const branding = useBranding()
  const { app_name, logo_url, primary_color, theme } = branding
  useEffect(() => {
    applyBranding({ app_name, logo_url, primary_color, theme })
  }, [app_name, logo_url, primary_color, theme])
  return null
}
