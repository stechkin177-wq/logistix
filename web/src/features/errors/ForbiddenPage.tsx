import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { EmptyState } from '../../shared/ui/EmptyState'

export function ForbiddenPage() {
  const { t } = useTranslation()
  return (
    <EmptyState title={t('errors.forbiddenTitle')} hint={t('errors.forbiddenHint')}>
      <Link to="/" className="mt-2 text-sm text-brand-700 underline dark:text-brand-300">
        {t('common.toHome')}
      </Link>
    </EmptyState>
  )
}
