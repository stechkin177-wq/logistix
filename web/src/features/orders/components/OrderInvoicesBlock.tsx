import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { Banner } from '../../../shared/ui/Banner'
import { Money } from '../../../shared/ui/Money'
import { Spinner } from '../../../shared/ui/Spinner'
import { useInvoices } from '../../finance/hooks'
import { fromCents, toCents } from '../../finance/invoiceMath'
import { StatusBadge, invoiceLabel } from '../../finance/StatusBadge'
import type { InvoiceListFilters } from '../../finance/types'
import type { Order } from '../types'

const sum = (values: string[]) => fromCents(values.reduce((acc, v) => acc + (toCents(v) ?? 0n), 0n))

/** Счета заказа: выставлено / доход / оплачено, список со ссылками и кнопка «Выставить счёт». Только для finance.view. */
export function OrderInvoicesBlock({ order, currency }: { order: Order; currency: string }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const filters: InvoiceListFilters = {
    direction: 'out', status: '', client: null, carrier: null, order: order.id, date_from: '', date_to: '', search: '', page: 1, pageSize: 100,
  }
  const list = useInvoices(filters, hasPermission('finance.view'))
  if (!hasPermission('finance.view')) return null
  const invoices = list.data?.results ?? []
  const active = invoices.filter((i) => i.status === 'issued')

  return (
    <section aria-label={t('finance.orderBlock.title')} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t('finance.orderBlock.title')}</h2>
        {hasPermission('finance.create') ? (
          <Link className="text-sm font-medium text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/new?order=${String(order.id)}`}>
            {t('finance.orderBlock.new')}
          </Link>
        ) : null}
      </div>
      {list.isPending ? <Spinner /> : null}
      {list.isError ? <Banner kind="error">{errorMessage(list.error, t)}</Banner> : null}
      {list.data ? (
        <>
          <dl className="grid grid-cols-3 gap-2 text-sm">
            <div><dt className="text-xs text-muted">{t('finance.orderBlock.invoiced')}</dt><dd><Money value={sum(active.map((i) => i.totals.net))} currency={currency} /></dd></div>
            <div><dt className="text-xs text-muted">{t('finance.orderBlock.income')}</dt><dd><Money value={order.revenue} currency={currency} /></dd></div>
            <div><dt className="text-xs text-muted">{t('finance.orderBlock.paid')}</dt><dd><Money value={sum(active.map((i) => i.paid))} currency={currency} /></dd></div>
          </dl>
          {invoices.length === 0 ? (
            <p className="text-sm text-muted">{t('finance.orderBlock.empty')}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {invoices.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-2">
                  <Link className="text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/${String(i.id)}`}>{invoiceLabel(i, t)}</Link>
                  <StatusBadge status={i.display_status} />
                  <Money value={i.totals.gross} currency={currency} />
                  <span className="text-xs text-muted">{t('finance.invoices.balance')}: <Money value={i.balance} currency={currency} /></span>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </section>
  )
}
