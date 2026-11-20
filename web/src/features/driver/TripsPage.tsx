import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { EmptyState } from '../../shared/ui/EmptyState'
import { SegmentedControl } from '../../shared/ui/SegmentedControl'
import { Spinner } from '../../shared/ui/Spinner'
import { Truck } from '../../shared/ui/icons'
import { useDriverTrips } from './hooks'
import { DRIVER_SCOPES, type DriverTrip } from './types'

const SCHEMA = { scope: codecs.oneOf(DRIVER_SCOPES, 'current') }
const TONE: Record<string, 'info' | 'success' | 'warning' | 'danger' | 'neutral'> = {
  IN_PROGRESS: 'info', UNLOADING: 'warning', COMPLETED: 'success', CANCELLED: 'danger',
}

export function TripCard({ trip }: { trip: DriverTrip }) {
  const { dateTime } = useFormat()
  return (
    <Link to={`/driver/trips/${String(trip.id)}`} className="block rounded-card border border-line bg-surface p-4 shadow-card active:bg-surface-2">
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold">{trip.number}</span>
        <Badge tone={TONE[trip.status.code] ?? 'neutral'}>{trip.status.name}</Badge>
      </div>
      <p className="mt-2 text-base">{trip.from_city || '-'} → {trip.to_city || '-'}</p>
      <p className="mt-1 text-sm text-muted">
        {[trip.vehicle_plate, trip.trailer_plate].filter(Boolean).join(' + ')}
        {trip.starts_at ? ` · ${dateTime(trip.starts_at)}` : ''}
      </p>
    </Link>
  )
}

/** «Мои рейсы»: текущий (в пути), предстоящие и история; карточки крупные, нажимаются пальцем. */
export function TripsPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  const list = useDriverTrips(state.scope)
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t('driver.tabs.trips')}</h1>
      <SegmentedControl
        label={t('driver.scopeLabel')}
        value={state.scope}
        options={DRIVER_SCOPES.map((s) => ({ value: s, label: t(`driver.scopes.${s}`) }))}
        onChange={(v) => { setState({ scope: DRIVER_SCOPES.find((s) => s === v) ?? 'current' }, { replace: true }) }}
      />
      {list.isPending ? <Spinner /> : null}
      {list.isError ? <Banner kind="error">{errorMessage(list.error, t)}</Banner> : null}
      {list.data?.results.length === 0 ? <EmptyState icon={Truck} title={t(`driver.empty.${state.scope}`)} hint={t('driver.emptyHint')} /> : null}
      {list.data?.results.map((trip) => <TripCard key={trip.id} trip={trip} />)}
    </div>
  )
}
