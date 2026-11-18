import { lazy, Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { useGeofences, useGpsUnits, useUnitTrack } from './hooks'

const GpsMap = lazy(() => import('./GpsMap'))

const today = () => new Date().toISOString().slice(0, 10)
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10)

/** Карта: позиции техники, геозоны и трек выбранного юнита за период. */
export function MapTab() {
  const { t } = useTranslation()
  const units = useGpsUnits({ page: 1 })
  const geofences = useGeofences(1, '')
  const [selected, setSelected] = useState<number | null>(null)
  const [from, setFrom] = useState(daysAgo(1))
  const [to, setTo] = useState(today())
  const [asked, setAsked] = useState<{ id: number; from: string; to: string } | null>(null)
  const track = useUnitTrack(asked?.id ?? null, asked?.from ?? '', asked?.to ?? '', asked !== null)
  const rows = units.data?.results ?? []
  const withPos = rows.filter((u) => u.lat && u.lon)
  const valid = selected !== null && from !== '' && to !== '' && from <= to
  const result = track.data
  const points = result?.available ? result.points : []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-3 shadow-card">
        <div className="w-56 max-sm:w-full">
          <Select
            label={t('gps.unit')}
            value={selected === null ? '' : String(selected)}
            placeholder={t('gps.pickUnit')}
            options={rows.map((u) => ({ value: String(u.id), label: u.vehicle_plate ? `${u.vehicle_plate} · ${u.name}` : u.name }))}
            onChange={(v) => { setSelected(v ? Number(v) : null); setAsked(null) }}
          />
        </div>
        <div className="w-40 max-sm:w-[calc(50%-0.375rem)]"><DateInput label={t('gps.trackFrom')} value={from} onChange={setFrom} /></div>
        <div className="w-40 max-sm:w-[calc(50%-0.375rem)]"><DateInput label={t('gps.trackTo')} value={to} onChange={setTo} /></div>
        <Button variant="primary" disabled={!valid || track.isFetching} onClick={() => { if (selected !== null) setAsked({ id: selected, from, to }) }}>
          {track.isFetching ? t('gps.loadingTrack') : t('gps.showTrack')}
        </Button>
        {asked ? <Button onClick={() => { setAsked(null) }}>{t('gps.clearTrack')}</Button> : null}
      </div>
      {track.isError ? <Banner kind="error">{errorMessage(track.error, t)}</Banner> : null}
      {result && !result.available ? <Banner kind="error">{t(`gps.trackReason.${result.reason || 'wialon_error'}`)}</Banner> : null}
      {result?.available ? (
        <Banner kind="info">{result.total_points === 0 ? t('gps.trackEmpty') : t('gps.trackSummary', { points: result.total_points, km: result.length_km ?? 0 })}</Banner>
      ) : null}
      {units.isSuccess && withPos.length === 0 ? <Banner kind="info">{t('gps.mapNoUnits')}</Banner> : null}
      <Suspense fallback={<div className="flex h-[26rem] items-center justify-center rounded-card border border-line"><Spinner /></div>}>
        <GpsMap units={rows} geofences={geofences.data?.results ?? []} track={points} selectedUnit={selected} onSelectUnit={(id) => { setSelected(id); setAsked(null) }} />
      </Suspense>
    </div>
  )
}
