import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateTime } from '../../shared/ui/DateTime'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Stat } from '../../shared/ui/Stat'
import { Activity, Building2, CircleAlert, Clock, Coins, LayoutDashboard, TrendingUp, Users, Wallet } from '../../shared/ui/icons'
import { useDashboard } from './hooks'
import type { DashboardCompanyRow, PlatformDashboard } from './types'

const STATUS_ORDER = ['active', 'trial', 'grace', 'readonly', 'blocked'] as const
const STATUS_COLOR: Record<(typeof STATUS_ORDER)[number], string> = {
  active: 'bg-emerald-500', trial: 'bg-sky-500', grace: 'bg-amber-400', readonly: 'bg-orange-500', blocked: 'bg-red-500',
}
const STATUS_TONE: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
  active: 'success', trial: 'info', grace: 'warning', readonly: 'warning', blocked: 'danger',
}

function Card({ title, icon: Icon, children, action }: { title: string; icon: typeof Wallet; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-surface p-3 shadow-card md:p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="size-4 text-muted" aria-hidden="true" />
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Месяц «2026-11» -> «ноя 26» по языку интерфейса. */
function useMonthLabel() {
  const { i18n } = useTranslation()
  return (ym: string) => {
    const [y, m] = ym.split('-').map(Number)
    return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, 1)).toLocaleDateString(i18n.language, { month: 'short', timeZone: 'UTC' }).replace('.', '')
  }
}

function RevenueChart({ data }: { data: PlatformDashboard['revenue'] }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const label = useMonthLabel()
  const max = Math.max(1, ...data.by_month.map((m) => Number(m.revenue)))
  const maxNew = Math.max(1, ...data.by_month.map((m) => m.new))
  return (
    <div>
      <ul aria-label={t('platform.dashboard.revenueByMonth')} className="grid h-40 grid-cols-12 items-end gap-1 sm:gap-2">
        {data.by_month.map((m) => {
          const h = Math.round((Number(m.revenue) / max) * 100)
          const nh = Math.round((m.new / maxNew) * 100)
          return (
            <li key={m.month} className="flex h-full min-w-0 flex-col items-center justify-end gap-1" title={`${m.month}: ${money(m.revenue, data.currency)}; ${t('platform.dashboard.newCompanies')}: ${m.new}`}>
              <div className="flex h-full w-full items-end justify-center gap-0.5">
                <span className="w-1/2 max-w-4 rounded-t bg-brand-500" style={{ height: `${Math.max(h, m.revenue === '0.00' || Number(m.revenue) === 0 ? 2 : 4)}%` }} />
                <span className="w-1/2 max-w-4 rounded-t bg-emerald-400" style={{ height: `${Math.max(nh, m.new === 0 ? 2 : 4)}%` }} />
              </div>
              <span className="text-[10px] leading-none text-muted">{label(m.month)}</span>
            </li>
          )
        })}
      </ul>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-brand-500" aria-hidden="true" />{t('platform.dashboard.revenue')}</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-emerald-400" aria-hidden="true" />{t('platform.dashboard.newCompanies')}</span>
      </p>
    </div>
  )
}

function CompanyList({ rows, empty }: { rows: DashboardCompanyRow[]; empty: string }) {
  const { t } = useTranslation()
  if (rows.length === 0) return <p className="text-sm text-muted">{empty}</p>
  return (
    <ul className="divide-y divide-line">
      {rows.map((r) => (
        <li key={r.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <Link to={`/platform/companies?q=${encodeURIComponent(r.name)}`} className="block truncate text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">{r.name}</Link>
            <p className="text-xs text-muted">{r.plan_name}</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{t(`company.statuses.${r.status}`)}</Badge>
            {r.ends_at ? <DateTime value={r.ends_at} dateOnly /> : null}
          </div>
        </li>
      ))}
    </ul>
  )
}

/** Главная страница Центра управления: сводная аналитика платформы (компании, подписки, выручка, тарифы, люди, действия). */
export function PlatformDashboardPage() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const q = useDashboard()
  const d = q.data
  const cur = d?.revenue.currency
  const live = d ? d.subscriptions.by_status.active + d.subscriptions.by_status.trial : 0
  const problem = d ? d.subscriptions.by_status.grace + d.subscriptions.by_status.readonly + d.subscriptions.by_status.blocked : 0
  const total = d?.subscriptions.total ?? 0

  return (
    <div className="space-y-3">
      <PageHeader icon={LayoutDashboard} title={t('platform.dashboard.title')} subtitle={d ? <>{t('platform.dashboard.updated')} <DateTime value={d.generated_at} /></> : undefined} />
      {q.isError ? (
        <Banner kind="error">{errorMessage(q.error, t)} <Button onClick={() => void q.refetch()}>{t('common.retry')}</Button></Banner>
      ) : null}
      {d ? (
        <>
          <section aria-label={t('platform.dashboard.kpi')} className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))]">
            <Stat icon={Building2} label={t('platform.dashboard.companies')} value={String(d.companies.total)} to="/platform/companies" sub={t('platform.dashboard.newInMonth', { count: d.companies.new_30d })} />
            <Stat icon={TrendingUp} label={t('platform.dashboard.liveSubs')} value={String(live)} to="/platform/companies?state=active" sub={t('platform.dashboard.ofTotal', { total })} />
            <Stat icon={Wallet} label={t('platform.dashboard.revenueMonth')} value={money(d.revenue.month, cur)} />
            <Stat icon={Coins} label={t('platform.dashboard.mrr')} value={money(d.revenue.mrr, cur)} sub={t('platform.dashboard.mrrHint')} />
            <Stat icon={Wallet} label={t('platform.dashboard.revenueYear')} value={money(d.revenue.year, cur)} />
            <Stat icon={Clock} label={t('platform.dashboard.expiring')} value={String(d.subscriptions.expiring_count)} sub={t('platform.dashboard.expiringHint')} tone={d.subscriptions.expiring_count > 0 ? undefined : 'success'} />
            <Stat icon={CircleAlert} label={t('platform.dashboard.problem')} value={String(problem)} to="/platform/companies?state=inactive" tone={problem > 0 ? 'danger' : 'success'} sub={t('platform.dashboard.problemHint')} />
            <Stat icon={Users} label={t('platform.dashboard.users')} value={String(d.users.total)} sub={t('platform.dashboard.perCompany', { value: d.users.per_company_avg })} />
          </section>

          <div className="grid gap-3 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Card title={t('platform.dashboard.revenueByMonth')} icon={TrendingUp}>
                <RevenueChart data={d.revenue} />
              </Card>
            </div>
            <Card title={t('platform.dashboard.byStatus')} icon={Activity}>
              <div role="img" aria-label={t('platform.dashboard.byStatus')} className="flex h-3 overflow-hidden rounded-full bg-surface-2">
                {STATUS_ORDER.map((s) => {
                  const n = d.subscriptions.by_status[s]
                  return n > 0 ? <span key={s} className={STATUS_COLOR[s]} style={{ width: `${(n / Math.max(total, 1)) * 100}%` }} /> : null
                })}
              </div>
              <ul className="mt-3 space-y-1.5 text-sm">
                {STATUS_ORDER.map((s) => (
                  <li key={s} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2"><span className={`size-2.5 rounded-full ${STATUS_COLOR[s]}`} aria-hidden="true" />{t(`company.statuses.${s}`)}</span>
                    <b className="tabular-nums">{d.subscriptions.by_status[s]}</b>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">{t('platform.dashboard.freePeriod', { count: d.subscriptions.free_period })}</p>
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title={t('platform.dashboard.byPlan')} icon={Wallet} action={<Link to="/platform/plans" className="text-xs text-brand-700 hover:underline dark:text-brand-300">{t('platform.dashboard.toPlans')}</Link>}>
              <ul className="space-y-3">
                {d.plans.map((p) => (
                  <li key={p.code}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="min-w-0 truncate font-medium">{p.name} <span className="text-xs font-normal text-muted">{money(p.price, p.currency)} / {t(`platform.plans.periods.${p.billing_type}`)}</span></span>
                      <span className="shrink-0 tabular-nums"><b>{p.subscriptions}</b> <span className="text-xs text-muted">({total ? Math.round((p.subscriptions / total) * 100) : 0}%)</span></span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                      <span className="block h-full rounded-full bg-brand-500" style={{ width: `${total ? (p.subscriptions / total) * 100 : 0}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title={t('platform.dashboard.activity')} icon={Activity} action={<Link to="/platform/history" className="text-xs text-brand-700 hover:underline dark:text-brand-300">{t('platform.dashboard.toHistory')}</Link>}>
              <p className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                <span>{t('platform.dashboard.logins7d')}: <b className="text-ink">{d.activity.logins_7d}</b></span>
                <span>{t('platform.dashboard.changes7d')}: <b className="text-ink">{d.activity.changes_7d}</b></span>
              </p>
              <ul className="divide-y divide-line">
                {d.activity.recent.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 py-1.5 text-xs first:pt-0 last:pb-0">
                    <span className="min-w-0 truncate text-sm text-ink">
                      {t(`platform.history.actions.${e.action}`, { defaultValue: e.action })}
                      <span className="text-muted"> · {t(`platform.history.kind.${e.kind}`)}</span>
                    </span>
                    <span className="flex items-center gap-2 text-muted"><span className="max-w-[10rem] truncate">{e.actor || '—'}</span><DateTime value={e.created_at} /></span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title={t('platform.dashboard.expiringList')} icon={Clock}>
              <CompanyList rows={d.subscriptions.expiring} empty={t('platform.dashboard.nothing')} />
            </Card>
            <Card title={t('platform.dashboard.problemList')} icon={CircleAlert}>
              <CompanyList rows={d.subscriptions.problem} empty={t('platform.dashboard.nothing')} />
            </Card>
          </div>
        </>
      ) : q.isFetching ? <p className="text-sm text-muted">{t('common.loading')}</p> : null}
    </div>
  )
}
