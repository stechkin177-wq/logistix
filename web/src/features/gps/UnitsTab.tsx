import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { Link2, RotateCcw } from '../../shared/ui/icons'
import { useVehicleList } from '../fleet/hooks'
import { useAutoLinkUnits, useGpsUnits, useLinkUnit, useSyncGps, useUnlinkUnit } from './hooks'
import type { GpsUnit } from './types'

const SCHEMA = { q: codecs.string(''), linked: codecs.oneOf(['', 'true', 'false'] as const, ''), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

const mapLink = (u: GpsUnit) => `https://www.openstreetmap.org/?mlat=${u.lat ?? ''}&mlon=${u.lon ?? ''}#map=14/${u.lat ?? ''}/${u.lon ?? ''}`

/** Юниты Wialon: последняя позиция, пробег и топливо по GPS; привязка юнита к технике парка. */
export function UnitsTab() {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useGpsUnits({ page: state.page, q: state.q, linked: state.linked })
  const vehicles = useVehicleList({ q: '', kind: '', status: '', ordering: 'plate', page: 1, pageSize: 200 })
  const sync = useSyncGps()
  const link = useLinkUnit()
  const unlink = useUnlinkUnit()
  const auto = useAutoLinkUnits()
  const [message, setMessage] = useState<string>()
  const taken = new Set((list.data?.results ?? []).map((u) => u.vehicle).filter((v): v is number => v !== null))
  const options = (vehicles.data?.results ?? []).map((v) => ({ value: String(v.id), label: v.plate }))

  const columns: Column<GpsUnit>[] = [
    { key: 'name', header: t('gps.unit'), cell: (u) => <span className="font-medium">{u.name}</span> },
    {
      key: 'vehicle',
      header: t('gps.vehicle'),
      cell: (u) =>
        u.vehicle !== null ? (
          <span className="flex items-center gap-2">
            <span>{u.vehicle_plate}</span>
            <WriteButton permission="gps.manage" className="h-7! px-2! text-xs!" onClick={() => { unlink.mutate(u.id) }}>{t('gps.unlink')}</WriteButton>
          </span>
        ) : (
          <Select
            label={t('gps.linkTo')}
            hideLabel
            value=""
            placeholder={t('gps.linkTo')}
            options={options.filter((o) => !taken.has(Number(o.value)))}
            onChange={(v) => { if (v) link.mutate({ id: u.id, vehicle: Number(v) }, { onError: (e) => { setMessage(errorMessage(e, t)) } }) }}
          />
        ),
    },
    {
      key: 'position',
      header: t('gps.position'),
      cell: (u) =>
        u.lat && u.lon ? (
          <span className="block">
            <a className="text-brand-700 hover:underline dark:text-brand-300" href={mapLink(u)} target="_blank" rel="noreferrer">
              {Number(u.lat).toFixed(4)}, {Number(u.lon).toFixed(4)}
            </a>
            <span className="block text-xs text-muted">{u.speed_kmh ?? 0} {t('gps.kmh')} · {dateTime(u.position_at)}</span>
            {u.location_text ? <span className="block text-xs text-muted">{u.location_text}</span> : null}
          </span>
        ) : '—',
    },
    { key: 'odometer', header: t('gps.odometer'), align: 'right', cell: (u) => (u.odometer_km ? `${Number(u.odometer_km).toLocaleString('ru-RU')} ${t('gps.km')}` : '—') },
    { key: 'fuel', header: t('gps.fuel'), align: 'right', cell: (u) => (u.fuel_level_l ? `${u.fuel_level_l} ${t('gps.litres')}` : '—') },
  ]

  return (
    <div className="space-y-3">
      <FilterBar
        search={<FilterItem className="w-auto"> <TextField label={t('common.search')} type="search" placeholder={t('gps.searchUnits')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} /> </FilterItem>}
        canReset={state.q !== '' || state.linked !== ''}
        onReset={() => { setState({ q: '', linked: '' }) }}
        actions={
          <>
            <WriteButton permission="gps.manage" icon={Link2} disabled={auto.isPending} onClick={() => { auto.mutate(undefined, { onSuccess: (r) => { setMessage(t('gps.autoLinked', { count: r.linked })) } }) }}>{t('gps.autoLink')}</WriteButton>
            <WriteButton permission="gps.manage" variant="primary" icon={RotateCcw} disabled={sync.isPending} onClick={() => { sync.mutate(undefined, { onSuccess: (r) => { setMessage(r.ok ? t('gps.synced', { units: r.units?.units_seen ?? 0 }) : r.error) }, onError: (e) => { setMessage(errorMessage(e, t)) } }) }}>
              {sync.isPending ? t('gps.syncing') : t('gps.sync')}
            </WriteButton>
          </>
        }
      >
        <FilterItem>
          <Select label={t('gps.linkFilter')} value={state.linked} placeholder={t('common.all')} options={[{ value: 'true', label: t('gps.linked') }, { value: 'false', label: t('gps.notLinked') }]} onChange={(v) => { setState({ linked: v === 'true' || v === 'false' ? v : '' }) }} />
        </FilterItem>
      </FilterBar>
      {message ? <Banner kind="info">{message}</Banner> : null}
      <DataTable
        caption={t('gps.tabs.units')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(u) => u.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('gps.unitsEmpty')} hint={t('gps.unitsEmptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
