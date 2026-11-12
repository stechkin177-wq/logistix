import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Combobox } from '../../../shared/ui/Combobox'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { Money } from '../../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../../shared/ui/Pagination'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { searchCarriers } from '../../carriers/api'
import { useCurrencies, usePartyOption } from '../../orders/hooks'
import { TripDrawer } from '../components/TripDrawer'
import { TripStatusControl } from '../components/TripStatusControl'
import { useTripList } from '../hooks'
import type { Trip } from '../types'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Route } from '../../../shared/ui/icons'

const SCHEMA = {
  q: codecs.string(''),
  order: codecs.id(),
  status: codecs.id(),
  carrier: codecs.id(),
  consolidated: codecs.flag(),
  open: codecs.id(), // карточка рейса открывается сразу (переход после «Создать рейс»)
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Рейсы: фильтры в адресе (q и order приходят по ссылкам со страницы заказа), статус на месте, карточка в Drawer. */
export function TripsPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useTripList(state)
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const statuses = useHandbookValues('trip_status')
  const { codeOf } = useCurrencies()
  const carrier = usePartyOption('carriers', state.carrier)
  const [openId, setOpenId] = useState<number | null>(state.open)
  const filtered = state.q !== '' || state.order !== null || state.status !== null || state.carrier !== null || state.consolidated
  const reset = () => { setState({ q: '', order: null, status: null, carrier: null, consolidated: false }) }

  const columns: Column<Trip>[] = [
    {
      key: 'number',
      header: t('trips.number'),
      cell: (trip) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setOpenId(trip.id) }}>
          {trip.number}
        </button>
      ),
    },
    { key: 'status', header: t('common.status'), cell: (trip) => <TripStatusControl trip={trip} /> },
    { key: 'carrier', header: t('trips.carrier'), cell: (trip) => trip.carrier_name ?? <Badge tone="warning">{t('orders.noCarrier')}</Badge> },
    { key: 'vehicle', header: t('trips.vehicleDriver'), cell: (trip) => [trip.vehicle_plate, trip.driver_name].filter(Boolean).join(' / ') || '—' },
    {
      key: 'orders',
      header: t('trips.orders'),
      cell: (trip) => (
        <span className="flex flex-wrap items-center gap-x-2">
          {trip.orders.map((o) => (
            <Link key={o.id} to={`/orders/${String(o.id)}`} className="text-brand-700 hover:underline dark:text-brand-300">{o.number}</Link>
          ))}
          {trip.is_consolidated ? <Badge tone="info">{t('trips.consolidatedShort')}</Badge> : null}
        </span>
      ),
    },
    { key: 'cargo', header: t('trips.cargo'), cell: (trip) => trip.consignments.map((c) => c.name).join(', ') || '—' },
    { key: 'carrier_price', header: t('trips.carrierPrice'), align: 'right', cell: (trip) => <Money value={trip.carrier_price} currency={codeOf(trip.currency) || undefined} /> },
  ]

  return (
    <div className="space-y-3">
      <PageHeader icon={Route} title={t('nav.trips')} />
      <FilterBar canReset={filtered} onReset={reset}>
        <FilterItem className="w-48">
          <TextField label={t('common.search')} type="search" placeholder={t('trips.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
        <FilterItem>
          <Select label={t('common.status')} value={state.status === null ? '' : String(state.status)} placeholder={t('common.all')} options={statuses.values.map((s) => ({ value: String(s.id), label: s.name }))} onChange={(v) => { setState({ status: v ? Number(v) : null }) }} />
        </FilterItem>
        <FilterItem className="w-56">
          <Combobox label={t('trips.carrier')} queryKey={['carriers', 'search']} fetchOptions={searchCarriers} value={carrier} onChange={(o) => { setState({ carrier: o?.id ?? null }) }} />
        </FilterItem>
        <FilterItem className="w-auto">
          <Checkbox label={t('trips.onlyConsolidated')} checked={state.consolidated} onChange={(e) => { setState({ consolidated: e.target.checked }) }} />
        </FilterItem>
        {state.order !== null ? (
          <FilterItem className="w-auto">
            <Badge tone="info">{t('trips.orderFilter', { id: state.order })}</Badge>
          </FilterItem>
        ) : null}
      </FilterBar>
      <DataTable
        caption={t('nav.trips')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(trip) => trip.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={reset}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('trips.empty')} hint={t('trips.emptyHint')}>
              <Link to="/consignments?withoutTrip=1" className="text-brand-700 hover:underline dark:text-brand-300">{t('trips.toQueue')}</Link>
            </EmptyState>
          )
        }
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {openId !== null ? <TripDrawer tripId={openId} onClose={() => { setOpenId(null) }} /> : null}
    </div>
  )
}
