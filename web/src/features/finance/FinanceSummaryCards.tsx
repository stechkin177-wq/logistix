import { useTranslation } from 'react-i18next'
import { useFormat } from '../../shared/format/useFormat'
import { Stat } from '../../shared/ui/Stat'
import { DebtsExcludedHint } from './DebtsExcludedHint'
import { useFinanceSummary } from './hooks'

/** Сводка на первом экране финансов: прибыль месяца, долги клиентов, просрочка, долг перевозчикам. */
export function FinanceSummaryCards() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const finance = useFinanceSummary().data
  if (!finance) return null
  const base = finance.base_currency
  const cur = base ?? finance.debts_currency ?? finance.currency
  const debt = base ? finance.client_debt_base : finance.client_debt_kzt
  const overdue = base ? finance.overdue_base : finance.overdue_kzt
  const payable = base ? finance.payable_base : finance.payable_kzt
  return (
    <section aria-label={t('finance.summaryTitle')} className="space-y-2">
      <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))]">
        <Stat
          label={t('dashboard.monthProfit')}
          value={money(finance.month_profit_kzt, finance.currency)}
          sub={finance.month_margin_pct === null ? undefined : t('dashboard.marginInline', { value: money(finance.month_margin_pct) })}
        />
        <Stat label={t('finance.dashboard.clientDebt')} value={money(debt, cur)} to="/finance?tab=debts" />
        <Stat label={t('finance.dashboard.overdue')} value={money(overdue, cur)} to="/finance?tab=invoices&status=overdue&direction=out" />
        <Stat label={t('finance.dashboard.payable')} value={money(payable, cur)} to="/finance?tab=debts&kind=carriers" />
      </div>
      {base ? <DebtsExcludedHint excluded={finance.debts_excluded} /> : null}
      {finance.is_partial ? <p className="text-xs text-amber-700 dark:text-amber-300">{t('finance.summaryPartial')}</p> : null}
    </section>
  )
}
