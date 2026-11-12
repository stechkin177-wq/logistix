import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { DateTime } from '../../../shared/ui/DateTime'
import { Select } from '../../../shared/ui/Select'
import { WriteButton } from '../../../shared/ui/WriteButton'
import type { OrderStop } from '../../orders/types'
import { useConsignmentTransfers, useCreateEvent, useEvents } from '../hooks'
import type { EventType } from '../types'
import { TransferDialog } from './TransferDialog'
import { TransferStatusBadge } from './TransferStatusBadge'

const EVENT_TYPES: EventType[] = ['arrived', 'loaded', 'departed', 'transferred', 'unloaded', 'delivered', 'skipped', 'stored']

/** Лента событий груза, его передачи и кнопки «Передать груз» / «Зафиксировать событие». */
export function CargoTracking({ consignmentId, stops }: { consignmentId: number; stops: OrderStop[] }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const events = useEvents(consignmentId)
  const transfers = useConsignmentTransfers(consignmentId)
  const addEvent = useCreateEvent(consignmentId)
  const [dialog, setDialog] = useState(false)
  const [eventType, setEventType] = useState<EventType>('arrived')
  const [stopId, setStopId] = useState(stops[0] ? String(stops[0].id) : '')
  const canTransfer = hasPermission('consignments.update') || hasPermission('consignments.transfer')

  return (
    <section aria-label={t('tracking.title')} className="space-y-2 rounded-control border border-line p-2 text-xs">
      <div className="flex flex-wrap items-end gap-2">
        {canTransfer ? (
          <Button onClick={() => { setDialog(true) }}>{t('tracking.transferButton')}</Button>
        ) : null}
        {hasPermission('consignments.update') ? (
          <>
            <Select
              label={t('tracking.eventType')}
              value={eventType}
              options={EVENT_TYPES.map((e) => ({ value: e, label: t(`tracking.eventTypes.${e}`) }))}
              onChange={(v) => { setEventType(v as EventType) }}
            />
            <Select
              label={t('tracking.stop')}
              value={stopId}
              options={stops.map((s) => ({ value: String(s.id), label: `${String(s.seq)}. ${s.city}` }))}
              onChange={setStopId}
            />
            <WriteButton permission="consignments.update" disabled={addEvent.isPending || !stopId} onClick={() => { addEvent.mutate({ event_type: eventType, stop: Number(stopId) }) }}>
              {t('tracking.addEvent')}
            </WriteButton>
          </>
        ) : null}
      </div>
      {addEvent.isError ? <Banner kind="error">{errorMessage(addEvent.error, t)}</Banner> : null}
      <h4 className="font-medium">{t('tracking.events')}</h4>
      {events.data && events.data.length > 0 ? (
        <ol aria-label={t('tracking.events')} className="space-y-0.5">
          {events.data.map((e) => (
            <li key={e.id}>
              <DateTime value={e.occurred_at} /> — {t(`tracking.eventTypes.${e.event_type}`)}
              {e.stop_city ? `, ${e.stop_city}` : ''}
              {e.source === 'driver_app' ? ` (${t('tracking.fromDriverApp')})` : ''}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted">{t('tracking.noEvents')}</p>
      )}
      {transfers.data && transfers.data.length > 0 ? (
        <>
          <h4 className="font-medium">{t('tracking.transfers')}</h4>
          <ul aria-label={t('tracking.transfers')} className="space-y-0.5">
            {transfers.data.map((x) => (
              <li key={x.id}>
                {t(`tracking.kinds.${x.transfer_kind}`)}, {x.to_stop_city} <TransferStatusBadge transfer={x} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {dialog ? <TransferDialog consignmentId={consignmentId} stops={stops} onClose={() => { setDialog(false) }} /> : null}
    </section>
  )
}
