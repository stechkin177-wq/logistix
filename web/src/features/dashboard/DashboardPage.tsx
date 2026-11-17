import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import type { DashboardSummary } from '../../shared/api/types'
import { useCanWrite } from '../../shared/auth/useCanWrite'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Plus } from '../../shared/ui/icons'
import { ExcludedHint } from '../../shared/ui/ExcludedHint'
import { Spinner } from '../../shared/ui/Spinner'
import { Stat } from '../../shared/ui/Stat'
import { useSession } from '../../shared/auth/useSession'
import { FinanceSummaryCards } from '../finance/FinanceSummaryCards'
import { useDashboardSummary } from './hooks'
import { PeriodPicker } from './PeriodPicker'
import { periodQuery, usePeriod } from './profitPeriod'
import { PageHeader } from '../../shared/ui/PageHeader'
import { LayoutDashboard } from '../../shared/ui/icons'

function StatusBars({ data }: { data: DashboardSummary }) {
  const { t } = useTranslation()
  const max = Math.max(0, ...data.orders_by_status.map((s) => s.count))
  return (
    <section aria-labelledby="by-status" className="rounded-card border border-line bg-surface p-4 shadow-card">
      <h2 id="by-status" className="mb-2 text-sm font-semibold">
        {t('dashboard.byStatus')}
      </h2>
      <ul className="space-y-1.5">
        {data.orders_by_status.map((row) => (
          <li key={row.status_id}>
            <Link to={`/orders?status=${row.status_id}`} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-2 text-sm hover:underline sm:grid-cols-[10rem_1fr_3rem]">
              <span className="truncate">{row.status}</span>
              <span className="h-2 rounded bg-slate-100 dark:bg-slate-800" aria-hidden="true">
                <span
                  className="block h-2 rounded bg-brand-500"
                  style={{ width: max > 0 ? `${String((row.count / max) * 100)}%` : '0%' }}
                />
              </span>
              <span className="text-right tabular-nums">{row.count}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function DashboardPage() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const canCreate = useCanWrite('orders.create')
  const { hasPermission, hasModule, session } = useSession()
  const [period] = usePeriod()
  const query = useDashboardSummary(true, periodQuery(period, session?.company.timezone ?? 'UTC') ?? undefined)
  const canFinance = hasPermission('finance.view') && hasModule('finance')
  const data = query.data
  // без модуля финансов остаётся прибыль из сводки заказов (за тот же период)
  const profitOnly = !canFinance && data !== undefined && data.month_profit !== null

  const empty =
    data !== undefined &&
    data.active_orders === 0 &&
    data.completed_orders === 0 &&
    data.clients === 0 &&
    data.carriers === 0 &&
    data.orders_by_status.every((s) => s.count === 0)

  return (
    <div className="space-y-4">
      <PageHeader icon={LayoutDashboard} title={t('nav.dashboard')} actions={canFinance || profitOnly ? <PeriodPicker /> : undefined} />
      {query.isPending ? <Spinner label={t('common.loading')} /> : null}
      {query.isError ? (
        <div className="space-y-2">
          <Banner kind="error">{errorMessage(query.error, t)}</Banner>
          <Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>
        </div>
      ) : null}
      {data ? (
        <>
          {/* сначала деньги: доход, расход, прибыль, просрочка, долги - за выбранный период */}
          {canFinance ? <FinanceSummaryCards withFx /> : null}
          {profitOnly ? (
            <section aria-label={t('dashboard.moneyTitle')} className="space-y-2">
              <h2 className="text-sm font-semibold">{t('dashboard.moneyTitle')}</h2>
              <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))]">
                <Stat
                  label={t('dashboard.profit')}
                  value={money(data.month_profit, data.currency ?? undefined)}
                  sub={data.month_margin_pct === null ? undefined : t('dashboard.marginInline', { value: money(data.month_margin_pct) })}
                />
              </div>
              {data.excluded ? <ExcludedHint excluded={data.excluded} /> : null}
              {!data.excluded && (data.excluded_orders ?? 0) > 0 ? (
                <p className="text-xs text-muted">{t('dashboard.excludedOrders', { count: data.excluded_orders ?? 0, currency: data.currency ?? '' })}</p>
              ) : null}
            </section>
          ) : null}
          {/* ниже - работа: заказы, клиенты, перевозчики */}
          <section aria-label={t('dashboard.workTitle')} className="space-y-2">
            <h2 className="text-sm font-semibold">{t('dashboard.workTitle')}</h2>
            <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))]">
              <Stat label={t('dashboard.activeOrders')} value={String(data.active_orders)} to="/orders" />
              <Stat label={t('dashboard.completedOrders')} value={String(data.completed_orders)} />
              <Stat label={t('dashboard.clients')} value={String(data.clients)} to="/clients" />
              <Stat label={t('dashboard.carriers')} value={String(data.carriers)} to="/carriers" />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/orders?unassigned=1"
                className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-900 hover:bg-amber-200 dark:bg-amber-950 dark:text-amber-100"
              >
                {t('dashboard.unassignedOrders')}
                <span className="tabular-nums">{data.unassigned_orders}</span>
              </Link>
            </div>
          </section>
          {empty ? (
            <EmptyState title={t('dashboard.emptyTitle')} hint={t('dashboard.emptyHint')}>
              {canCreate ? (
                <Link to="/orders/new" className="inline-flex h-9 items-center justify-center gap-1.5 rounded-control bg-brand-600 px-3.5 text-sm font-medium text-brand-fg shadow-sm transition-colors hover:bg-brand-solid-hover">
                  <Plus className="size-4" aria-hidden="true" />
                  {t('orders.new')}
                </Link>
              ) : null}
            </EmptyState>
          ) : null}
          <StatusBars data={data} />
        </>
      ) : null}
    </div>
  )
}
