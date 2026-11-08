import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, type Tone } from '../../../shared/ui/Badge'
import type { TripLeg, TripLegStatus } from '../types'

const TONES: Record<TripLegStatus, Tone> = { planned: 'neutral', in_progress: 'info', done: 'success', cancelled: 'danger' }

/** Доли участка словами; пусто по всем измерениям - весь груз. */
function shares(leg: TripLeg, t: (key: string) => string): string {
  const parts = [
    leg.weight_kg !== null ? `${leg.weight_kg} ${t('consignments.kg')}` : '',
    leg.volume_m3 !== null ? `${leg.volume_m3} ${t('consignments.m3')}` : '',
    leg.pallets !== null ? `${String(leg.pallets)} ${t('trips.palletsShort')}` : '',
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : t('trips.wholeCargo')
}

/** Участки рейса: груз, откуда - куда, доли, статус. */
export function TripLegs({ legs }: { legs: TripLeg[] }) {
  const { t } = useTranslation()
  if (legs.length === 0) return null
  return (
    <section aria-labelledby="trip-legs" className="mt-4 space-y-1">
      <h3 id="trip-legs" className="text-xs font-medium">{t('trips.legs')}</h3>
      <ul className="divide-y divide-slate-100 rounded border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-700">
        {legs.map((leg) => (
          <li key={leg.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-2 py-1">
            <span className="min-w-0">
              <span className="font-medium">{leg.consignment_name}</span>{' '}
              <Link to={`/orders/${String(leg.order)}`} className="text-xs text-brand-700 hover:underline dark:text-brand-300">{leg.order_number}</Link>
              <br />
              <span className="text-xs text-slate-600 dark:text-slate-300">
                {leg.from_stop && leg.to_stop ? `${leg.from_stop.city} → ${leg.to_stop.city}` : t('trips.wholeRoute')}
                {' · '}
                {shares(leg, t)}
              </span>
            </span>
            <Badge tone={TONES[leg.status]}>{t(`trips.legStatus.${leg.status}`)}</Badge>
          </li>
        ))}
      </ul>
    </section>
  )
}
