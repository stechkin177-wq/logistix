import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Dialog } from '../../../shared/ui/Dialog'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import { useChangeTripStatus } from '../hooks'
import type { Trip } from '../types'

/** Системный код статуса «Завершён»: выход из него требует права и причины. */
const COMPLETED = 'COMPLETED'
const REVERT_PERMISSION = 'trips.revert_completed'
/** Обычный путь рейса: одна кнопка следующего шага по коду статуса (остальные переходы - в списке). */
const FLOW = ['PLANNED', 'ASSIGNED', 'IN_PROGRESS', 'UNLOADING', 'COMPLETED']
/** Шаги, при которых можно сразу внести официальный пробег (выезд и завершение). */
const ODOMETER_STEPS = ['IN_PROGRESS', 'COMPLETED']

/**
 * Статус рейса: с правом trips.update - выпадающий список (POST /trips/{id}/status/), иначе значок.
 * Выход из «Завершён» доступен только с правом trips.revert_completed и запрашивает причину.
 */
export function TripStatusControl({ trip }: { trip: Pick<Trip, 'id' | 'number' | 'status' | 'status_name'> }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const canUpdate = useCanWrite('trips.update')
  const statuses = useHandbookValues('trip_status')
  const change = useChangeTripStatus()
  const [pending, setPending] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | undefined>()
  const [odo, setOdo] = useState<{ status: number; code: string } | null>(null)
  const [vehicleKm, setVehicleKm] = useState('')
  const [trailerKm, setTrailerKm] = useState('')
  if (!canUpdate || statuses.all.length === 0) return <Badge tone="info">{trip.status_name}</Badge>

  const current = statuses.all.find((s) => s.id === trip.status)
  const leavingLocked = current?.code === COMPLETED && !hasPermission(REVERT_PERMISSION)
  const target = pending === null ? undefined : statuses.all.find((s) => s.id === pending)
  // следующий шаг: ближайший по обычному пути статус, который есть в справочнике компании
  const flowIndex = FLOW.indexOf(current?.code ?? '')
  const nextStatus = flowIndex < 0 ? undefined : FLOW.slice(flowIndex + 1)
    .map((code) => statuses.all.find((s) => s.code === code && s.is_active))
    .find((s) => s !== undefined)
  const closeOdo = () => { setOdo(null); setVehicleKm(''); setTrailerKm(''); setError(undefined); change.reset() }
  const submitOdo = () => {
    if (!odo) return
    const km = (v: string) => (v.trim() === '' ? undefined : Number(v))
    const values = { vehicle_km: km(vehicleKm), trailer_km: km(trailerKm) }
    if (Object.values(values).some((v) => v !== undefined && (!Number.isInteger(v) || v < 0))) { setError(t('trips.odometerInvalid')); return }
    change.mutate(
      { id: trip.id, status: odo.status, ...(values.vehicle_km !== undefined ? { vehicle_km: values.vehicle_km } : {}), ...(values.trailer_km !== undefined ? { trailer_km: values.trailer_km } : {}) },
      { onSuccess: closeOdo, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }
  const stepForward = () => {
    if (!nextStatus) return
    if (ODOMETER_STEPS.includes(nextStatus.code) && !(nextStatus.code === 'IN_PROGRESS' && current?.code === 'UNLOADING')) {
      setOdo({ status: nextStatus.id, code: nextStatus.code })
      return
    }
    change.mutate({ id: trip.id, status: nextStatus.id }, { onError: (e) => { pushToast('error', errorMessage(e, t)) } })
  }
  const close = () => { setPending(null); setReason(''); setError(undefined); change.reset() }

  const submitRevert = () => {
    if (pending === null) return
    if (!reason.trim()) { setError(t('trips.revertReasonRequired')); return }
    change.mutate(
      { id: trip.id, status: pending, reason: reason.trim() },
      { onSuccess: close, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }

  return (
    <>
      {nextStatus ? (
        <Button variant="primary" onClick={stepForward} disabled={change.isPending}>
          {t('trips.nextStep', { status: nextStatus.name })}
        </Button>
      ) : null}
      <select
        aria-label={t('trips.statusOf', { number: trip.number })}
        value={trip.status}
        disabled={change.isPending}
        title={leavingLocked ? t('trips.revertNoPermission') : undefined}
        onChange={(event) => {
          const next = Number(event.target.value)
          if (current?.code === COMPLETED) {
            setPending(next) // причина обязательна: ставим статус только после диалога
            return
          }
          change.mutate({ id: trip.id, status: next }, { onError: (e) => { pushToast('error', errorMessage(e, t)) } })
        }}
        className="h-8 rounded border border-slate-300 bg-white px-1.5 text-xs dark:border-slate-600 dark:bg-slate-900"
      >
        {selectableValues(statuses.all, trip.status).map((s) => (
          <option key={s.id} value={s.id} disabled={leavingLocked && s.id !== trip.status}>{s.name}</option>
        ))}
      </select>
      <Dialog
        open={odo !== null}
        title={t('trips.odometerTitle', { status: statuses.all.find((x) => x.id === odo?.status)?.name ?? '' })}
        onClose={closeOdo}
        busy={change.isPending}
        footer={
          <>
            <Button onClick={closeOdo} disabled={change.isPending}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={submitOdo} disabled={change.isPending}>{t('trips.odometerConfirm')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          {error ? <Banner kind="error">{error}</Banner> : null}
          <p className="text-sm text-slate-600 dark:text-slate-300">{t('trips.odometerHint')}</p>
          <TextField label={t('trips.vehicleKm')} inputMode="numeric" value={vehicleKm} onChange={(e) => { setVehicleKm(e.target.value) }} />
          <TextField label={t('trips.trailerKm')} inputMode="numeric" value={trailerKm} onChange={(e) => { setTrailerKm(e.target.value) }} />
        </div>
      </Dialog>
      <Dialog
        open={pending !== null}
        title={t('trips.revertTitle')}
        onClose={close}
        busy={change.isPending}
        footer={
          <>
            <Button onClick={close} disabled={change.isPending}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={submitRevert} disabled={change.isPending}>{t('trips.revertConfirm')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          {error ? <Banner kind="error">{error}</Banner> : null}
          <p className="text-sm">{t('trips.revertMessage', { number: trip.number, status: target?.name ?? '' })}</p>
          <TextArea
            label={t('trips.revertReason')}
            required
            value={reason}
            maxLength={1000}
            onChange={(e) => { setReason(e.target.value) }}
          />
        </div>
      </Dialog>
    </>
  )
}
