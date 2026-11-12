import { useTranslation } from 'react-i18next'
import { Badge } from '../../../shared/ui/Badge'
import { Card } from '../../../shared/ui/Card'
import { DateTime } from '../../../shared/ui/DateTime'
import { Money } from '../../../shared/ui/Money'
import { useCurrencies } from '../hooks'
import type { Order, TripRef } from '../types'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  )
}

/** Самая ранняя плановая погрузка среди грузов заказа (по точкам погрузки). */
export function plannedLoading(order: Order): string | null {
  const times = order.consignments
    .flatMap((c) => c.points)
    .filter((p) => p.kind === 'load' && p.window_from)
    .map((p) => p.window_from)
    .sort()
  return times[0] ?? null
}

/** Сводка заказа над вкладками: маршрут, состав, перевозчики, плановая погрузка, ставка и маржа. */
export function OrderSummary({ order, trips, showMargin }: { order: Order; trips: TripRef[]; showMargin: boolean }) {
  const { t } = useTranslation()
  const { codeOf } = useCurrencies()
  const carriers = [...new Set(trips.map((x) => x.carrier_name).filter((n): n is string => n !== null && n !== ''))]
  const loading = plannedLoading(order)
  const loss = order.profit !== null && Number(order.profit) < 0
  return (
    <Card>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
        <Fact label={t('orders.route')}>{order.route || '—'}</Fact>
        <Fact label={t('orders.summaryComposition')}>{t('orders.summaryCompositionValue', { cargo: order.consignments.length, trips: trips.length })}</Fact>
        <Fact label={t('orders.summaryCarriers')}>
          {carriers.length > 0 ? (
            <span className="flex flex-wrap gap-x-2">
              {carriers.map((name) => (
                <span key={name}>{name}</span>
              ))}
            </span>
          ) : (
            <Badge tone="warning">{t('orders.noCarrier')}</Badge>
          )}
        </Fact>
        <Fact label={t('orders.summaryLoading')}>{loading ? <DateTime value={loading} /> : '—'}</Fact>
        <Fact label={t('orders.clientRate')}><Money value={order.client_rate} currency={codeOf(order.currency) || undefined} /></Fact>
        {showMargin && order.profit !== null ? (
          <Fact label={t('orders.summaryMargin')}>
            <span className={loss ? 'text-red-600 dark:text-red-400' : undefined}>
              <Money value={order.profit} currency={codeOf(order.currency) || undefined} />
              {order.margin_pct !== null ? ` · ${order.margin_pct} %` : ''}
            </span>
          </Fact>
        ) : null}
      </dl>
    </Card>
  )
}
