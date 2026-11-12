import { useTranslation } from 'react-i18next'
import type { OrderStop } from '../types'

interface Props {
  stops: Pick<OrderStop, 'kind' | 'city' | 'status'>[]
}

/** Маршрут цепочкой: Город (вид) → Город (вид) → ...; выполненные остановки отмечены. */
export function RouteChain({ stops }: Props) {
  const { t } = useTranslation()
  if (stops.length === 0) return null
  return (
    <ol aria-label={t('orders.routeChain')} className="flex flex-wrap items-center gap-1 text-xs">
      {stops.map((stop, index) => (
        <li key={index} className="flex items-center gap-1">
          {index > 0 ? <span aria-hidden="true" className="text-slate-400">→</span> : null}
          <span className={`rounded px-1.5 py-0.5 ${stop.status === 'done' ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-slate-100 dark:bg-slate-800'}`}>
            <span className="font-medium">{stop.city}</span>
            <span className="text-muted"> · {t(`orders.stopKinds.${stop.kind}`)}</span>
          </span>
        </li>
      ))}
    </ol>
  )
}
