import { useTranslation } from 'react-i18next'
import { useFormat } from '../../shared/format/useFormat'
import { useSession } from '../../shared/auth/useSession'
import { Stat } from '../../shared/ui/Stat'
import { financePeriodQuery, usePeriod } from '../dashboard/profitPeriod'
import { DebtsExcludedHint } from './DebtsExcludedHint'
import { useFinanceSummary } from './hooks'

const ruDate = (iso: string) => iso.split('-').reverse().join('.')

/**
 * Финансовые показатели за выбранный период: общий доход, общий расход, прибыль с маржой, просрочено,
 * долг клиентов и к оплате перевозчикам (долги - на конец периода). Период выбирается значком-фильтром
 * (PeriodPicker) и действует на дашборде и в «Финансах» одинаково. withFx добавляет курсовые разницы.
 */
export function FinanceSummaryCards({ withFx = false, className = '' }: { withFx?: boolean; className?: string }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const { session } = useSession()
  const [period] = usePeriod()
  const finance = useFinanceSummary(true, financePeriodQuery(period, session?.company.timezone ?? 'UTC') ?? undefined).data
  if (!finance) return null
  const base = finance.base_currency
  const debtsCur = base ?? finance.debts_currency ?? finance.currency
  const debt = base ? finance.client_debt_base : finance.client_debt_kzt
  const overdue = base ? finance.overdue_base : finance.overdue_kzt
  const payable = base ? finance.payable_base : finance.payable_kzt
  const range = finance.period_from && finance.period_to ? `${ruDate(finance.period_from)} – ${ruDate(finance.period_to)}` : null
  return (
    <section aria-label={t('finance.summaryTitle')} className={`space-y-2 ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-sm font-semibold">{t('dashboard.moneyTitle')}</h2>
        <p className="text-xs text-muted">
          {period.preset === 'custom' ? t('dashboard.periodCustomName') : t(`dashboard.periodPreset.${period.preset}`)}
          {range ? ` · ${range}` : ''}
        </p>
      </div>
      <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))]">
        {finance.income_kzt !== undefined ? <Stat label={t('dashboard.totalIncome')} value={money(finance.income_kzt, finance.currency)} to="/finance?tab=incomes" /> : null}
        {finance.expense_kzt !== undefined ? <Stat label={t('dashboard.totalExpense')} value={money(finance.expense_kzt, finance.currency)} to="/finance?tab=expenses" /> : null}
        <Stat
          label={t('dashboard.profit')}
          value={money(finance.month_profit_kzt, finance.currency)}
          tone={Number(finance.month_profit_kzt) < 0 ? 'danger' : undefined}
          to="/finance?tab=operations"
          sub={finance.month_margin_pct === null ? undefined : t('dashboard.marginInline', { value: money(finance.month_margin_pct) })}
        />
        <Stat label={t('finance.dashboard.overdue')} value={money(overdue, debtsCur)} to="/finance?tab=invoices&status=overdue&direction=out" />
        <Stat label={t('finance.dashboard.clientDebt')} value={money(debt, debtsCur)} to="/finance?tab=debts" />
        <Stat label={t('finance.dashboard.payable')} value={money(payable, debtsCur)} to="/finance?tab=debts&kind=carriers" />
        {withFx && base ? (
          <>
            <Stat label={t('finance.fx.dashboardRealized')} value={money(finance.fx_realized_base, base)} to="/finance?tab=payments" />
            <Stat label={t('finance.fx.dashboardUnrealized')} value={money(finance.fx_unrealized_base, base)} to="/finance?tab=debts" />
          </>
        ) : null}
      </div>
      {period.preset !== 'month' ? <p className="text-xs text-muted">{t('dashboard.debtsAsOfEnd')}</p> : null}
      {base ? <DebtsExcludedHint excluded={finance.debts_excluded} /> : null}
      {withFx && finance.fx_realized_partial ? <p className="text-xs text-amber-700 dark:text-amber-300">{t('finance.fx.realizedPartial')}</p> : null}
      {finance.is_partial ? <p className="text-xs text-amber-700 dark:text-amber-300">{t('finance.summaryPartial')}</p> : null}
    </section>
  )
}
