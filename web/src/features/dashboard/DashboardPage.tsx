import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import type { DashboardSummary } from '../../shared/api/types'
import { useCanWrite } from '../../shared/auth/useCanWrite'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { EmptyState } from '../../shared/ui/EmptyState'
import { ExcludedHint } from '../../shared/ui/ExcludedHint'
import { Spinner } from '../../shared/ui/Spinner'
import { Stat } from '../../shared/ui/Stat'
import { useSession } from '../../shared/auth/useSession'
import { DebtsExcludedHint } from '../finance/DebtsExcludedHint'
import { useFinanceSummary } from '../finance/hooks'
import { useDashboardSummary } from './hooks'

function StatusBars({ data }: { data: DashboardSummary }) {
  const { t } = useTranslation()
  const max = Math.max(0, ...data.orders_by_status.map((s) => s.count))
  return (
    <section aria-labelledby="by-status" className="rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
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
  const query = useDashboardSummary()
  const { hasPermission, hasModule } = useSession()
  const canFinance = hasPermission('finance.view') && hasModule('finance')
  const finance = useFinanceSummary(canFinance).data
  const data = query.data

  const empty =
    data !== undefined &&
    data.active_orders === 0 &&
    data.completed_orders === 0 &&
    data.clients === 0 &&
    data.carriers === 0 &&
    data.orders_by_status.every((s) => s.count === 0)

  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.dashboard')}</h1>
      {query.isPending ? <Spinner label={t('common.loading')} /> : null}
      {query.isError ? (
        <div className="space-y-2">
          <Banner kind="error">{errorMessage(query.error, t)}</Banner>
          <Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>
        </div>
      ) : null}
      {data ? (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label={t('dashboard.activeOrders')} value={String(data.active_orders)} to="/orders" />
            <Stat label={t('dashboard.completedOrders')} value={String(data.completed_orders)} />
            <Stat label={t('dashboard.clients')} value={String(data.clients)} to="/clients" />
            <Stat label={t('dashboard.carriers')} value={String(data.carriers)} to="/carriers" />
          </div>
          {data.month_profit !== null ? (
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Stat label={t('dashboard.monthProfit')} value={money(data.month_profit, data.currency ?? undefined)} />
              <Stat
                label={t('dashboard.monthMargin')}
                value={data.month_margin_pct === null ? '—' : `${money(data.month_margin_pct)} %`}
              />
            </div>
          ) : null}
          {canFinance && finance ? (
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {finance.base_currency ? (
                <>
                  <Stat label={t('finance.dashboard.clientDebt')} value={money(finance.client_debt_base, finance.base_currency)} to="/finance?tab=debts" />
                  <Stat label={t('finance.dashboard.overdue')} value={money(finance.overdue_base, finance.base_currency)} to="/finance?tab=invoices&status=overdue&direction=out" />
                  <Stat label={t('finance.dashboard.payable')} value={money(finance.payable_base, finance.base_currency)} to="/finance?tab=debts&kind=carriers" />
                  <Stat label={t('finance.fx.dashboardRealized')} value={money(finance.fx_realized_base, finance.base_currency)} to="/finance?tab=payments" />
                  <Stat label={t('finance.fx.dashboardUnrealized')} value={money(finance.fx_unrealized_base, finance.base_currency)} to="/finance?tab=debts" />
                </>
              ) : (
                <>
                  <Stat label={t('finance.dashboard.clientDebt')} value={money(finance.client_debt_kzt, finance.debts_currency ?? finance.currency)} to="/finance?tab=debts" />
                  <Stat label={t('finance.dashboard.overdue')} value={money(finance.overdue_kzt, finance.debts_currency ?? finance.currency)} to="/finance?tab=invoices&status=overdue&direction=out" />
                  <Stat label={t('finance.dashboard.payable')} value={money(finance.payable_kzt, finance.debts_currency ?? finance.currency)} to="/finance?tab=debts&kind=carriers" />
                </>
              )}
            </div>
          ) : null}
          {canFinance && finance?.base_currency ? <DebtsExcludedHint excluded={finance.debts_excluded} /> : null}
          {canFinance && finance?.fx_realized_partial ? <p className="text-xs text-amber-700 dark:text-amber-300">{t('finance.fx.realizedPartial')}</p> : null}
          {data.month_profit !== null && data.excluded ? <ExcludedHint excluded={data.excluded} /> : null}
          {data.month_profit !== null && !data.excluded && (data.excluded_orders ?? 0) > 0 ? (
            <p className="text-xs text-slate-500">
              {t('dashboard.excludedOrders', { count: data.excluded_orders ?? 0, currency: data.currency ?? '' })}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/orders?unassigned=1"
              className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-900 hover:bg-amber-200 dark:bg-amber-950 dark:text-amber-100"
            >
              {t('dashboard.unassignedOrders')}
              <span className="tabular-nums">{data.unassigned_orders}</span>
            </Link>
          </div>
          {empty ? (
            <EmptyState title={t('dashboard.emptyTitle')} hint={t('dashboard.emptyHint')}>
              {canCreate ? (
                <Link to="/orders/new" className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">
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
