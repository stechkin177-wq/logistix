import { useTranslation } from 'react-i18next'
import { Button } from '../../shared/ui/Button'

/** Полноэкранная заглушка при subscription_blocked. Запросов к API нет, только выход. */
export function BlockedPage({ onLogout }: { onLogout: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-3 bg-canvas p-4 text-center">
      <h1 className="text-xl font-semibold">{t('blocked.title')}</h1>
      <p className="max-w-md text-sm text-muted">{t('blocked.text')}</p>
      <Button variant="primary" onClick={onLogout}>
        {t('auth.logout')}
      </Button>
    </div>
  )
}
