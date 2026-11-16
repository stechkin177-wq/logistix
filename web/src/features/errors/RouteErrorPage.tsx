import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Button } from '../../shared/ui/Button'
import { EmptyState } from '../../shared/ui/EmptyState'
import { TriangleAlert } from '../../shared/ui/icons'

/** Запасной экран для непредвиденной ошибки отрисовки: вместо технической страницы роутера. */
export function RouteErrorPage() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas p-4 text-ink">
      <div className="w-full max-w-md rounded-card border border-line bg-surface shadow-card">
        <EmptyState heading icon={TriangleAlert} title={t('errors.crashTitle')} hint={t('errors.crashHint')}>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={() => { window.location.reload() }}>{t('errors.crashReload')}</Button>
            <Link to="/" reloadDocument className="inline-flex h-9 items-center rounded-control border border-line bg-surface px-3.5 text-sm font-medium shadow-sm hover:bg-surface-2">
              {t('common.toHome')}
            </Link>
          </div>
        </EmptyState>
      </div>
    </div>
  )
}
