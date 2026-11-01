import { Navigate, Outlet, useLocation } from 'react-router'
import { useTranslation } from 'react-i18next'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { loginPath } from './redirect'
import { useSession } from './useSession'

export function RequireAuth() {
  const { t } = useTranslation()
  const location = useLocation()
  const { status, refetch } = useSession()

  if (status === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner label={t('common.loading')} />
      </div>
    )
  }
  if (status === 'anonymous') {
    return <Navigate to={loginPath(location.pathname + location.search)} replace />
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
