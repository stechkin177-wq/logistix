import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { Badge } from '../../../shared/ui/Badge'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { useTripsOfOrder } from '../hooks'
import type { Order, TripRef } from '../types'

/** Рейсы с грузом заказа - только чтение; страницы рейсов появятся в 16b, ссылка ведёт в список с поиском по номеру. */
export function TripsTab({ order }: { order: Order }) {
  const { t } = useTranslation()
  const trips = useTripsOfOrder(order, true)
  const columns: Column<TripRef>[] = [
    {
      key: 'number',
      header: t('orders.tripNumber'),
      cell: (trip) => (
        <Link to={`/trips?q=${encodeURIComponent(trip.number)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
          {trip.number}
        </Link>
      ),
    },
    { key: 'carrier', header: t('orders.carrier'), cell: (trip) => trip.carrier_name ?? <Badge tone="warning">{t('orders.noCarrier')}</Badge> },
    { key: 'vehicle', header: t('orders.vehicle'), cell: (trip) => [trip.vehicle_plate, trip.driver_name].filter(Boolean).join(' / ') || '—' },
    { key: 'status', header: t('common.status'), cell: (trip) => <Badge>{trip.status_name}</Badge> },
    { key: 'consolidated', header: t('orders.consolidated'), cell: (trip) => (trip.is_consolidated ? t('common.yes') : t('common.no')) },
  ]
  return (
    <DataTable
      caption={t('orders.tabTrips')}
      columns={columns}
      rows={trips.data}
      rowKey={(trip) => trip.id}
      loading={trips.isFetching}
      error={trips.isError ? errorMessage(trips.error, t) : undefined}
      onRetry={() => void trips.refetch()}
      empty={<EmptyState title={t('orders.noTrips')} hint={t('orders.noTripsHint')} />}
    />
  )
}
