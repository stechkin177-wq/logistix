import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../shared/api/client'
import { errorMessage } from '../../shared/api/errors'
import type { DashboardSummary } from '../../shared/api/types'
import { Banner } from '../../shared/ui/Banner'
import { Spinner } from '../../shared/ui/Spinner'

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  )
}

/** Минимальная заглушка: числа сводки. Настоящий дашборд делает Task 16. */
export function DashboardPage() {
  const { t } = useTranslation()
  const query = useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: () => api.get<DashboardSummary>('/dashboard/summary/'),
  })

  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.dashboard')}</h1>
      {query.isPending ? <Spinner label={t('common.loading')} /> : null}
      {query.isError ? <Banner kind="error">{errorMessage(query.error, t)}</Banner> : null}
      {query.data ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <Stat label={t('dashboard.activeOrders')} value={query.data.active_orders} />
          <Stat label={t('dashboard.completedOrders')} value={query.data.completed_orders} />
          <Stat label={t('dashboard.unassignedOrders')} value={query.data.unassigned_orders} />
          <Stat label={t('dashboard.clients')} value={query.data.clients} />
          <Stat label={t('dashboard.carriers')} value={query.data.carriers} />
          {query.data.month_profit !== null ? (
            <Stat label={t('dashboard.monthProfit')} value={query.data.month_profit} />
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
