import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { Banner } from '../../../shared/ui/Banner'
import { Badge } from '../../../shared/ui/Badge'
import { DateTime } from '../../../shared/ui/DateTime'
import { Spinner } from '../../../shared/ui/Spinner'

interface Subscription {
  plan: { code: string; name: string }
  status: string
  is_free_period: boolean
  ends_at: string | null
  days_left: number | null
}

/** Лицензия: тариф, статус, срок, бесплатный период (GET /billing/subscription/). */
export function SubscriptionBlock() {
  const { t } = useTranslation()
  const query = useQuery({ queryKey: ['billing', 'subscription'], queryFn: ({ signal }) => api.get<Subscription>('/billing/subscription/', undefined, { signal }) })
  const sub = query.data
  return (
    <section aria-labelledby="license-title" className="space-y-2 rounded-card border border-line bg-surface p-4 shadow-card">
      <h2 id="license-title" className="text-sm font-semibold">{t('company.license')}</h2>
      {query.isError ? <Banner kind="error">{errorMessage(query.error, t)}</Banner> : null}
      {!sub && !query.isError ? <Spinner label={t('table.loading')} /> : null}
      {sub ? (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          <div><dt className="text-xs text-muted">{t('company.plan')}</dt><dd>{sub.plan.name}</dd></div>
          <div>
            <dt className="text-xs text-muted">{t('common.status')}</dt>
            <dd><Badge tone={sub.status === 'blocked' || sub.status === 'readonly' ? 'danger' : sub.status === 'grace' ? 'warning' : 'success'}>{t(`company.statuses.${sub.status}`)}</Badge></dd>
          </div>
          <div><dt className="text-xs text-muted">{t('company.endsAt')}</dt><dd>{sub.ends_at ? <DateTime value={sub.ends_at} dateOnly /> : t('company.unlimited')}</dd></div>
          <div><dt className="text-xs text-muted">{t('company.daysLeft')}</dt><dd>{sub.days_left ?? '—'}</dd></div>
          {sub.is_free_period ? <div className="sm:col-span-2"><Badge tone="info">{t('company.freePeriod')}</Badge></div> : null}
        </dl>
      ) : null}
    </section>
  )
}
