import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { DateTime } from '../../../shared/ui/DateTime'
import { Money } from '../../../shared/ui/Money'
import { Spinner } from '../../../shared/ui/Spinner'
import { useOrderBoard } from '../hooks'
import type { BoardCard, OrderListFilters } from '../types'
import { StatusControl } from './StatusControl'

function Card({ card, statusId, statusName }: { card: BoardCard; statusId: number; statusName: string }) {
  const { t } = useTranslation()
  return (
    <li className="space-y-1 rounded border border-slate-200 bg-white p-2 text-xs shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <Link to={`/orders/${String(card.id)}`} className="block text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">
        {card.number}
      </Link>
      <p className="truncate">{card.client}</p>
      {card.route ? <p className="truncate text-slate-500">{card.route}</p> : null}
      <p className="flex flex-wrap items-center gap-1">
        {card.carriers.length > 0 ? <span className="truncate">{card.carriers.join(', ')}</span> : <Badge tone="warning">{t('orders.noCarrier')}</Badge>}
      </p>
      <p className="flex justify-between gap-2 text-slate-600 dark:text-slate-300">
        <Money value={card.rate} currency={card.currency} />
        {card.loading_at ? <DateTime value={card.loading_at} /> : null}
      </p>
      <StatusControl compact orderId={card.id} number={card.number} statusId={statusId} statusName={statusName} />
    </li>
  )
}

/** Канбан: колонка на каждый статус (пустые тоже), счётчик, пометка «показаны не все»; смена статуса - в карточке. */
export function OrdersBoard({ filters }: { filters: OrderListFilters }) {
  const { t } = useTranslation()
  const board = useOrderBoard(filters, true)
  if (board.isError) {
    return (
      <div className="space-y-2">
        <Banner kind="error">{errorMessage(board.error, t)}</Banner>
        <Button onClick={() => void board.refetch()}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!board.data) return <Spinner label={t('common.loading')} />
  return (
    <div className="flex gap-3 overflow-x-auto pb-2" aria-busy={board.isFetching ? true : undefined}>
      {board.data.map((column) => (
        <section key={column.status.id} aria-label={column.status.name} className="w-64 shrink-0 rounded bg-slate-100 p-2 dark:bg-slate-800">
          <h3 className="mb-2 flex items-center justify-between text-xs font-semibold uppercase text-slate-600 dark:text-slate-300">
            <span className="truncate">{column.status.name}</span>
            <span className="rounded-full bg-white px-2 py-0.5 tabular-nums dark:bg-slate-900" aria-label={t('orders.columnCount', { count: column.count })}>{column.count}</span>
          </h3>
          {column.orders.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-500">{t('orders.columnEmpty')}</p>
          ) : (
            <ul className="space-y-2">
              {column.orders.map((card) => (
                <Card key={card.id} card={card} statusId={column.status.id} statusName={column.status.name} />
              ))}
            </ul>
          )}
          {column.has_more ? (
            <p className="mt-2 text-xs text-slate-500">{t('orders.hasMore', { shown: column.orders.length, total: column.count })}</p>
          ) : null}
        </section>
      ))}
    </div>
  )
}
