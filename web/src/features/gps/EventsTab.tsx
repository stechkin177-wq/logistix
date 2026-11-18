import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { useGeofenceEvents } from './hooks'
import type { GeofenceEvent } from './types'

const SCHEMA = { event_type: codecs.oneOf(['', 'enter', 'exit'] as const, ''), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

/** События геозон: въезд и выезд техники (справочно, к рейсу автоматически не привязываются). */
export function EventsTab() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useGeofenceEvents({ page: state.page, event_type: state.event_type })
  const columns: Column<GeofenceEvent>[] = [
    { key: 'when', header: t('gps.when'), cell: (e) => <DateTime value={e.occurred_at} /> },
    { key: 'vehicle', header: t('gps.vehicle'), cell: (e) => <span className="font-medium">{e.vehicle_plate}</span> },
    { key: 'type', header: t('gps.event'), cell: (e) => <Badge tone={e.event_type === 'enter' ? 'success' : 'neutral'}>{t(`gps.eventTypes.${e.event_type}`)}</Badge> },
    { key: 'zone', header: t('gps.geofence'), cell: (e) => e.geofence_name },
  ]
  return (
    <div className="space-y-3">
      <FilterBar canReset={state.event_type !== ''} onReset={() => { setState({ event_type: '' }) }}>
        <FilterItem>
          <Select label={t('gps.event')} value={state.event_type} placeholder={t('common.all')} options={[{ value: 'enter', label: t('gps.eventTypes.enter') }, { value: 'exit', label: t('gps.eventTypes.exit') }]} onChange={(v) => { setState({ event_type: v === 'enter' || v === 'exit' ? v : '' }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('gps.tabs.events')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(e) => e.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('gps.eventsEmpty')} hint={t('gps.eventsEmptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
