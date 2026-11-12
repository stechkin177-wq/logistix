import { Navigate, Outlet, useLocation } from 'react-router'
import { useTranslation } from 'react-i18next'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { loginPath } from './redirect'
import { useAuth } from './useAuth'
import { usePlatformSession } from './usePlatformSession'

/** Охранник маршрутов /platform: только платформенный контекст. Сервер проверяет всё равно. */
export function RequirePlatform() {
  const { t } = useTranslation()
  const location = useLocation()
  const { context } = useAuth()
  const { status, refetch } = usePlatformSession()

  if (status === 'anonymous') {
    return <Navigate to={loginPath(location.pathname + location.search)} replace />
  }
  if (context !== 'platform') return <Navigate to="/" replace />
  if (status === 'loading') {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner label={t('common.loading')} />
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="mx-auto mt-16 max-w-md space-y-3 p-4">
        <Banner kind="error">{t('errors.sessionLoad')}</Banner>
        <Button onClick={refetch}>{t('common.retry')}</Button>
      </div>
    )
  }
  return <Outlet />
}
