import { useEffect } from 'react'
import { Outlet } from 'react-router'
import { AuthProvider } from '../shared/auth/AuthProvider'
import { useSession } from '../shared/auth/useSession'
import { BrandingEffect } from '../shared/branding/useBranding'
import { applyCompanyLanguage } from '../shared/i18n'

function LanguageEffect(): null {
  const { session } = useSession()
  const language = session?.company.language
  useEffect(() => {
    if (language) applyCompanyLanguage(language)
  }, [language])
  return null
}

/** Корень маршрутов: провайдер входа (ему нужен router) и эффекты оформления/языка. */
export function RootRoute() {
  return (
    <AuthProvider>
      <BrandingEffect />
      <LanguageEffect />
      <Outlet />
    </AuthProvider>
  )
}
