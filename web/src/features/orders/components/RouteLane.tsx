import { useTranslation } from 'react-i18next'
import { Badge } from '../../../shared/ui/Badge'
import type { ConsignmentRoute } from '../types'

/**
 * Лента маршрута груза с покрытием: остановки по порядку, между ними - отрезки. Покрытый отрезок
 * показывает номера рейсов, непокрытый подсвечен («Рейс не назначен»). Итог - плашка над лентой.
 */
export function RouteLane({ route }: { route: ConsignmentRoute }) {
  const { t } = useTranslation()
  const { stops, coverage } = route
  if (stops.length === 0) return null
  const missing = coverage.uncovered.length
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium">{t('orders.routeChain')}</span>
        {coverage.fully_assigned ? (
          <Badge tone="success">{t('orders.routeAssigned')}</Badge>
        ) : (
          <Badge tone="warning">{t('orders.routeUnassigned', { count: missing || Math.max(stops.length - 1, 1) })}</Badge>
        )}
      </div>
      <ol aria-label={t('orders.routeLane')} className="flex flex-wrap items-stretch gap-y-1 text-xs">
        {stops.map((stop, index) => {
          const segment = index > 0 ? coverage.segments.find((s) => s.to_stop === stop.id) : undefined
          return (
            <li key={stop.id} className="flex items-center">
              {segment ? (
                <span
                  data-covered={segment.covered ? 'yes' : 'no'}
                  className={`mx-1 rounded px-1.5 py-0.5 ${
                    segment.covered
                      ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                      : 'bg-amber-100 font-medium text-amber-900 ring-1 ring-amber-400 dark:bg-amber-950 dark:text-amber-100'
                  }`}
                >
                  {segment.covered
                    ? segment.trips.length > 0
                      ? segment.trips.map((trip) => trip.number).join(', ')
                      : t('orders.segmentCovered')
                    : t('orders.segmentUncovered')}
                </span>
              ) : null}
              <span className="rounded bg-slate-100 px-1.5 py-0.5 dark:bg-slate-800">
                <span className="font-medium">{stop.city}</span>
                <span className="text-slate-500"> · {t(`orders.stopKinds.${stop.kind}`)}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
