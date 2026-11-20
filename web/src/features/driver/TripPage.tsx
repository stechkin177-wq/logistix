import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { ArrowLeft, Phone } from '../../shared/ui/icons'
import { useDriverTrip, useTripAction } from './hooks'
import type { DriverAction, DriverTripDetail } from './types'

const ODOMETER_ACTIONS: DriverAction[] = ['start', 'complete']

function ActionBar({ trip }: { trip: DriverTripDetail }) {
  const { t } = useTranslation()
  const run = useTripAction(trip.id)
  const [pending, setPending] = useState<DriverAction | null>(null)
  const [vehicleKm, setVehicleKm] = useState('')
  const [trailerKm, setTrailerKm] = useState('')
  const close = () => { setPending(null); setVehicleKm(''); setTrailerKm(''); run.reset() }
  const submit = () => {
    if (!pending) return
    const body: { action: DriverAction; vehicle_km?: number; trailer_km?: number } = { action: pending }
    if (ODOMETER_ACTIONS.includes(pending)) {
      if (vehicleKm.trim() !== '') body.vehicle_km = Number(vehicleKm)
      if (trailerKm.trim() !== '') body.trailer_km = Number(trailerKm)
    }
    run.mutate(body, { onSuccess: close })
  }
  if (trip.actions.length === 0) return null
  return (
    <>
      <div className="grid gap-2">
        {trip.actions.map((a) => (
          <Button key={a} variant={a === 'unloading' ? 'secondary' : 'primary'} className="h-14! text-base!" onClick={() => { setPending(a) }}>
            {t(`driver.actions.${a}`)}
          </Button>
        ))}
      </div>
      <Dialog
        open={pending !== null}
        title={pending ? t(`driver.actions.${pending}`) : ''}
        onClose={close}
        busy={run.isPending}
        footer={
          <>
            <Button onClick={close} disabled={run.isPending}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={submit} disabled={run.isPending}>{run.isPending ? t('common.saving') : t('driver.confirm')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          {run.isError ? <Banner kind="error">{errorMessage(run.error, t)}</Banner> : null}
          {pending && ODOMETER_ACTIONS.includes(pending) ? (
            <>
              <p className="text-sm text-muted">{t('driver.odometerHint')}</p>
              <TextField label={t('driver.vehicleKm')} inputMode="numeric" pattern="[0-9]*" value={vehicleKm} onChange={(e) => { setVehicleKm(e.target.value.replace(/\D/g, '')) }} />
              {trip.trailer_plate ? <TextField label={t('driver.trailerKm')} inputMode="numeric" pattern="[0-9]*" value={trailerKm} onChange={(e) => { setTrailerKm(e.target.value.replace(/\D/g, '')) }} /> : null}
            </>
          ) : (
            <p className="text-sm">{t('driver.confirmText')}</p>
          )}
        </div>
      </Dialog>
    </>
  )
}

/** Карточка рейса: маршрут по остановкам, грузы и крупные кнопки действий по статусу. */
export function TripPage() {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const id = Number(useParams().id)
  const query = useDriverTrip(id)
  if (query.isPending) return <Spinner />
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  const trip = query.data
  return (
    <div className="space-y-4">
      <Link to="/driver" className="inline-flex items-center gap-1 text-sm text-brand-700 dark:text-brand-300"><ArrowLeft className="size-4" aria-hidden="true" />{t('driver.tabs.trips')}</Link>
      <div>
        <div className="flex items-start justify-between gap-2">
          <h1 className="text-lg font-semibold">{trip.number}</h1>
          <Badge tone="info">{trip.status.name}</Badge>
        </div>
        <p className="mt-1 text-sm text-muted">{[trip.vehicle_plate, trip.trailer_plate].filter(Boolean).join(' + ')}</p>
      </div>
      <ActionBar trip={trip} />
      <section aria-label={t('driver.route')}>
        <h2 className="mb-2 text-sm font-semibold">{t('driver.route')}</h2>
        <ol className="space-y-2">
          {trip.stops.map((s) => (
            <li key={s.id} className="rounded-card border border-line bg-surface p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{s.city || '-'}</span>
                <span className="text-xs text-muted">{t(`driver.stopKinds.${s.kind}`, s.kind)}</span>
              </div>
              {s.street ? <p className="text-sm">{s.street}</p> : null}
              <p className="text-xs text-muted">{dateTime(s.window_from)}{s.window_to ? ` - ${dateTime(s.window_to)}` : ''}</p>
              {s.contact ? <p className="mt-1 flex items-center gap-1 text-sm"><Phone className="size-4 text-muted" aria-hidden="true" />{s.contact}</p> : null}
              {s.note ? <p className="mt-1 text-xs text-muted">{s.note}</p> : null}
            </li>
          ))}
        </ol>
        {trip.stops.length === 0 ? <p className="text-sm text-muted">{t('driver.noStops')}</p> : null}
      </section>
      <section aria-label={t('driver.cargo')}>
        <h2 className="mb-2 text-sm font-semibold">{t('driver.cargo')}</h2>
        <ul className="space-y-1 text-sm">
          {trip.consignments.map((c, i) => <li key={`${c.name}-${String(i)}`}>{c.name}{c.weight_kg ? ` · ${c.weight_kg} ${t('driver.kg')}` : ''}</li>)}
        </ul>
      </section>
    </div>
  )
}
