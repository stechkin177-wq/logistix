import { useTranslation } from 'react-i18next'
import { useSession } from '../shared/auth/useSession'
import { Banner } from '../shared/ui/Banner'

export function ReadonlyBanner() {
  const { t } = useTranslation()
  const { session, subscriptionStatus } = useSession()
  if (subscriptionStatus === 'grace') {
    const days = session?.subscription.grace_days_left ?? 0
    return <Banner kind="warning">{t('readonly.grace', { days })}</Banner>
  }
  if (subscriptionStatus === 'readonly') return <Banner kind="warning">{t('readonly.readonly')}</Banner>
  return null
}
