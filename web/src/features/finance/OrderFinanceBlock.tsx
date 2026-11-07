import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Money } from '../../shared/ui/Money'
import { Spinner } from '../../shared/ui/Spinner'
import { ExpenseStatusBadge, IncomeStatusBadge, ReviewBadge } from './LedgerBadges'
import { useOrderFinance } from './ledgerHooks'

/** «Финансы заказа» (engine = new): доходы, расходы с долями этого заказа, счета, итоги, проверка. */
export function OrderFinanceBlock({ orderId }: { orderId: number }) {
  const { t } = useTranslation()
  const query = useOrderFinance(orderId)
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner label={t('table.loading')} />
  const d = query.data
  const cur = d.order.currency?.code
  return (
    <section aria-labelledby="order-finance" className="space-y-3">
      <h3 id="order-finance" className="text-sm font-semibold">{t('finance.ledger.orderTitle')}</h3>
      {d.needs_review ? <Banner kind="warning">{t('finance.ledger.orderNeedsReview')}</Banner> : null}
      <div role="group" aria-label={t('finance.operations.summary')} className="grid gap-2 sm:grid-cols-4">
        {(['revenue', 'cost', 'profit'] as const).map((key) => (
          <div key={key} className="rounded border border-slate-200 p-2 dark:border-slate-700">
            <p className="text-xs text-slate-500">{t(`finance.ledger.totals.${key}`)}</p>
            <p className="text-base font-semibold tabular-nums"><Money value={d.totals[key]} currency={cur} /></p>
          </div>
        ))}
        <div className="rounded border border-slate-200 p-2 dark:border-slate-700">
          <p className="text-xs text-slate-500">{t('finance.ledger.totals.margin')}</p>
          <p className="text-base font-semibold tabular-nums">{d.totals.margin_pct === null ? '—' : `${d.totals.margin_pct}%`}</p>
        </div>
      </div>
      <div>
        <h4 className="text-xs font-medium">{t('finance.tabs.incomes')}</h4>
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {d.incomes.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-1">
              <span>{i.title}</span>
              <span className="flex items-center gap-2"><IncomeStatusBadge status={i.status} /><Money value={i.amount} currency={i.currency?.code} /></span>
            </li>
          ))}
          {d.incomes.length === 0 ? <li className="py-1 text-slate-500">{t('finance.ledger.noIncomes')}</li> : null}
        </ul>
      </div>
      <div>
        <h4 className="text-xs font-medium">{t('finance.tabs.expenses')}</h4>
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {d.expenses.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 py-1">
              <span>{e.title}</span>
              <span className="flex items-center gap-2">
                <ExpenseStatusBadge status={e.status} />
                <ReviewBadge expense={e} />
                <Money value={e.order_amount ?? e.amount} currency={e.currency?.code} />
              </span>
            </li>
          ))}
          {d.expenses.length === 0 ? <li className="py-1 text-slate-500">{t('finance.ledger.noExpenses')}</li> : null}
        </ul>
      </div>
      {d.invoices.length > 0 ? (
        <div>
          <h4 className="text-xs font-medium">{t('finance.tabs.invoices')}</h4>
          <ul className="text-sm">
            {d.invoices.map((i) => (
              <li key={i.id}>
                <Link className="text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/${String(i.id)}`}>{i.number || `#${String(i.id)}`}</Link>{' '}
                <Money value={i.total_gross} currency={i.currency?.code} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
