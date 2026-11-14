import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Lock } from '../../shared/ui/icons'

export function ForbiddenPage() {
  const { t } = useTranslation()
  return (
    <EmptyState heading icon={Lock} title={t('errors.forbiddenTitle')} hint={t('errors.forbiddenHint')}>
      <Link to="/" className="mt-2 text-sm text-brand-700 underline dark:text-brand-300">
        {t('common.toHome')}
      </Link>
    </EmptyState>
  )
}
