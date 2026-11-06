import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from '../api/client'
import type { Branding } from '../api/types'
import { useSession } from '../auth/useSession'
import { DEFAULT_BRANDING, applyBranding, sanitizeBranding } from './applyBranding'

function publicBranding(): Promise<Branding> {
  return api.get<Branding>('/branding/', { host: window.location.hostname }, { auth: false })
}

/**
 * До входа - публичное оформление по домену; после входа - оформление компании из сессии
 * (отдельный запрос company/branding не нужен: он требует company.view, которого нет у многих ролей).
 */
export function useBranding(): Branding {
  const { session } = useSession()
  const query = useQuery({
    queryKey: ['branding', 'public'],
    queryFn: publicBranding,
    enabled: !session,
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (session) return sanitizeBranding(session.branding)
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
