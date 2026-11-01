import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/ui/EmptyState'

/** Финансы: счета и платежи появятся на следующем этапе; интерфейс не выдумываем. */
export function FinancePage() {
  const { t } = useTranslation()
  return (
    <div>
      <h1 className="text-base font-semibold">{t('nav.finance')}</h1>
      <EmptyState title={t('finance.title')} hint={t('finance.hint')} />
    </div>
  )
}
