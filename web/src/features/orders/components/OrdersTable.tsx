import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { Badge } from '../../../shared/ui/Badge'
import { Button } from '../../../shared/ui/Button'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { Money } from '../../../shared/ui/Money'
import { Pagination } from '../../../shared/ui/Pagination'
import { useCurrencies, useOrderList } from '../hooks'
import type { Order, OrderListParams } from '../types'
import { NewOrderLink } from './NewOrderLink'
import { StatusControl } from './StatusControl'

/** Самая ранняя погрузка заказа по его грузам (как считает бэкенд для фильтра/канбана). */
export function loadingAt(order: Order): string | null {
  let best: string | null = null
  for (const c of order.consignments) {
    for (const p of c.points) {
      if (p.kind === 'load' && (best === null || p.window_from < best)) best = p.window_from
    }
  }
  return best
}

interface Props {
  params: OrderListParams
  filtered: boolean
  onChange: (patch: Partial<OrderListParams>) => void
  onReset: () => void
}

export function OrdersTable({ params, filtered, onChange, onReset }: Props) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const list = useOrderList(params)
  usePageFallback(list.error, params.page, () => { onChange({ page: 1 }) })
  const { codeOf } = useCurrencies()
  const rows = list.data?.results
  const showFinance = hasPermission('finance.view') && (rows ?? []).some((o) => o.cost !== null)

  const columns: Column<Order>[] = [
    {
      key: 'number',
      header: t('orders.number'),
      sortKey: 'number',
      cell: (o) => (
        <Link to={`/orders/${String(o.id)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
          {o.number}
        </Link>
      ),
    },
    { key: 'client', header: t('orders.client'), cell: (o) => o.client_name },
    { key: 'route', header: t('orders.route'), cell: (o) => o.route || '—' },
    {
      key: 'carrier',
      header: t('orders.carrier'),
      cell: (o) => (o.has_carrier ? <Badge tone="success">{t('orders.carrierAssigned')}</Badge> : <Badge tone="warning">{t('orders.noCarrier')}</Badge>),
    },
    {
      key: 'status',
      header: t('common.status'),
      cell: (o) => <StatusControl orderId={o.id} number={o.number} statusId={o.status} statusName={o.status_name} />,
    },
    { key: 'loading', header: t('orders.loading'), cell: (o) => <DateTime value={loadingAt(o)} /> },
    {
      key: 'rate',
      header: t('orders.rate'),
      align: 'right',
      cell: (o) => <Money value={o.client_rate} currency={codeOf(o.currency)} />,
    },
    ...(showFinance
      ? ([
          { key: 'cost', header: t('orders.cost'), align: 'right', cell: (o: Order) => <Money value={o.cost} /> },
          { key: 'profit', header: t('orders.profit'), align: 'right', cell: (o: Order) => <Money value={o.profit} /> },
        ] satisfies Column<Order>[])
      : []),
    { key: 'created', header: t('parties.created'), sortKey: 'created_at', cell: (o) => <DateTime value={o.created_at} dateOnly /> },
  ]

  return (
    <>
      <DataTable
        caption={t('nav.orders')}
        columns={columns}
        rows={rows}
        rowKey={(o) => o.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        ordering={params.ordering}
        onOrderingChange={(ordering) => { onChange({ ordering }) }}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={onReset}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('orders.empty')} hint={t('orders.emptyHint')}>
              <NewOrderLink />
            </EmptyState>
          )
        }
      />
      <Pagination
        page={params.page}
        pageSize={params.pageSize}
        count={list.data?.count ?? 0}
        onPage={(page) => { onChange({ page }) }}
        onPageSize={(pageSize) => { onChange({ pageSize }) }}
      />
    </>
  )
}
