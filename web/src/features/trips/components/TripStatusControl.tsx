import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Badge } from '../../../shared/ui/Badge'
import { pushToast } from '../../../shared/ui/toast'
import { useChangeTripStatus } from '../hooks'
import type { Trip } from '../types'

/** Статус рейса: с правом trips.update - выпадающий список (POST /trips/{id}/status/), иначе значок. */
export function TripStatusControl({ trip }: { trip: Pick<Trip, 'id' | 'number' | 'status' | 'status_name'> }) {
  const { t } = useTranslation()
  const canUpdate = useCanWrite('trips.update')
  const statuses = useHandbookValues('trip_status')
  const change = useChangeTripStatus()
  if (!canUpdate || statuses.all.length === 0) return <Badge tone="info">{trip.status_name}</Badge>
  return (
    <select
      aria-label={t('trips.statusOf', { number: trip.number })}
      value={trip.status}
      disabled={change.isPending}
      onChange={(event) => {
        change.mutate(
          { id: trip.id, status: Number(event.target.value) },
          { onError: (error) => { pushToast('error', errorMessage(error, t)) } },
        )
      }}
      className="h-7 rounded border border-slate-300 bg-white px-1.5 text-xs dark:border-slate-600 dark:bg-slate-900"
    >
      {selectableValues(statuses.all, trip.status).map((s) => (
        <option key={s.id} value={s.id}>{s.name}</option>
      ))}
    </select>
  )
}
