import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/ui/EmptyState'

/** Заглушка раздела; Task 16 заменяет её настоящими страницами. */
export function PlaceholderPage({ titleKey }: { titleKey: string }) {
  const { t } = useTranslation()
  return (
    <div>
      <h1 className="text-base font-semibold">{t(titleKey)}</h1>
      <EmptyState title={t('placeholder.title')} />
    </div>
  )
}
