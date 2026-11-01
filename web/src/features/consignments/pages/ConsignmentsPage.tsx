import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Combobox } from '../../../shared/ui/Combobox'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../../shared/ui/Pagination'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { searchClients } from '../../clients/api'
import { usePartyOption } from '../../orders/hooks'
import { CreateTripDrawer } from '../components/CreateTripDrawer'
import { useConsignmentList } from '../hooks'
import type { Consignment } from '../types'

const SCHEMA = {
  q: codecs.string(''),
  client: codecs.id(),
  withoutTrip: codecs.flag(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

const place = (c: Consignment, kind: 'load' | 'unload') => c.points.find((p) => p.kind === kind)

/** Грузы: очередь распределения по рейсам, выбор строк и создание (в том числе сборного) рейса. */
export function ConsignmentsPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useConsignmentList(state)
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const client = usePartyOption('clients', state.client)
  // выбор переживает смену страницы и фильтров: храним сами грузы, а не только id
  const [selected, setSelected] = useState<Map<number, Consignment>>(new Map())
  const [creating, setCreating] = useState(false)
  const rows = list.data?.results
  const filtered = state.q !== '' || state.client !== null || state.withoutTrip
  const allOnPage = (rows ?? []).length > 0 && (rows ?? []).every((c) => selected.has(c.id))

  const toggle = (c: Consignment) => {
    setSelected((prev) => {
      const next = new Map(prev)
      if (next.has(c.id)) next.delete(c.id)
      else next.set(c.id, c)
      return next
    })
  }
  const togglePage = () => {
    setSelected((prev) => {
      const next = new Map(prev)
      for (const c of rows ?? []) {
        if (allOnPage) next.delete(c.id)
        else next.set(c.id, c)
      }
      return next
    })
  }
  const reset = () => { setState({ q: '', client: null, withoutTrip: false }) }

  const columns: Column<Consignment>[] = [
    {
      key: 'select',
      header: <Checkbox label={t('consignments.selectPage')} hideLabel checked={allOnPage} disabled={(rows ?? []).length === 0} onChange={togglePage} />,
      headerLabel: t('consignments.selectPage'),
      cell: (c) => <Checkbox label={t('consignments.selectNamed', { name: c.name })} hideLabel checked={selected.has(c.id)} onChange={() => { toggle(c) }} />,
    },
    { key: 'name', header: t('consignments.cargo'), cell: (c) => <span className="font-medium">{c.name}</span> },
    {
      key: 'route',
      header: t('consignments.route'),
      cell: (c) => `${place(c, 'load')?.city ?? '—'} → ${place(c, 'unload')?.city ?? '—'}`,
    },
    {
      key: 'order',
      header: t('consignments.order'),
      cell: (c) => (
        <Link to={`/orders/${String(c.order)}`} className="text-brand-700 hover:underline dark:text-brand-300">
          {c.order_number}
        </Link>
      ),
    },
    { key: 'client', header: t('consignments.client'), cell: (c) => c.client_name },
    {
      key: 'size',
      header: t('consignments.weightVolume'),
      align: 'right',
      cell: (c) => <span className="whitespace-nowrap tabular-nums">{`${c.weight_kg} ${t('consignments.kg')} / ${c.volume_m3} ${t('consignments.m3')}`}</span>,
    },
    { key: 'loading', header: t('consignments.loading'), cell: (c) => <DateTime value={place(c, 'load')?.window_from} /> },
    {
      key: 'trips',
      header: t('consignments.trips'),
      align: 'right',
      cell: (c) => (c.trips_count === 0 ? <Badge tone="warning">{t('consignments.noTrip')}</Badge> : <span className="tabular-nums">{c.trips_count}</span>),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.consignments')}</h1>
        <div className="flex items-center gap-2">
          {selected.size > 0 ? (
            <>
              <span className="text-xs" aria-live="polite">{t('consignments.selectedCount', { count: selected.size })}</span>
              <Button variant="ghost" onClick={() => { setSelected(new Map()) }}>{t('consignments.clearSelection')}</Button>
            </>
          ) : null}
          <WriteButton permission="trips.create" variant="primary" disabled={selected.size === 0} onClick={() => { setCreating(true) }}>
            {t('consignments.createTrip')}
          </WriteButton>
        </div>
      </div>
      <FilterBar canReset={filtered} onReset={reset}>
        <FilterItem className="w-48">
          <TextField label={t('common.search')} type="search" placeholder={t('consignments.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
        <FilterItem className="w-56">
          <Combobox label={t('consignments.client')} queryKey={['clients', 'search']} fetchOptions={searchClients} value={client} onChange={(o) => { setState({ client: o?.id ?? null }) }} />
        </FilterItem>
        <FilterItem className="w-auto">
          <Checkbox label={t('consignments.queue')} checked={state.withoutTrip} onChange={(e) => { setState({ withoutTrip: e.target.checked }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('nav.consignments')}
        columns={columns}
        rows={rows}
        rowKey={(c) => c.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={reset}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('consignments.empty')} hint={t('consignments.emptyHint')} />
          )
        }
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {creating ? (
        <CreateTripDrawer
          selected={[...selected.values()]}
          onClose={() => { setCreating(false) }}
          onCreated={() => { setCreating(false); setSelected(new Map()) }}
        />
      ) : null}
    </div>
  )
}
