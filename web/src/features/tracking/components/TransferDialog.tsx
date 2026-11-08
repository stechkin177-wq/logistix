import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { fromInputDateTime, toInputDateTime } from '../../../shared/format/datetime'
import { Button } from '../../../shared/ui/Button'
import { Combobox, type ComboOption } from '../../../shared/ui/Combobox'
import { DateInput } from '../../../shared/ui/DateInput'
import { Dialog } from '../../../shared/ui/Dialog'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { searchActiveCarriers } from '../../trips/api'
import type { OrderStop } from '../../orders/types'
import { useCreateTransfer } from '../hooks'
import { TRANSFER_KINDS, type TransferKind } from '../types'

interface Props {
  consignmentId: number
  /** Остановки маршрута груза: передача возможна только на остановке вида «передача». */
  stops: OrderStop[]
  onClose: () => void
}

/** Диалог «Передать груз»: вид, остановка, рейсы (необязательно), перевозчик, время, заметка. */
export function TransferDialog({ consignmentId, stops, onClose }: Props) {
  const { t } = useTranslation()
  const { session } = useSession()
  const tz = session?.company.timezone
  const transferStops = stops.filter((s) => s.kind === 'transfer')
  const [kind, setKind] = useState<TransferKind>('to_storage')
  const [stopId, setStopId] = useState(transferStops[0] ? String(transferStops[0].id) : '')
  const [fromTrip, setFromTrip] = useState('')
  const [toTrip, setToTrip] = useState('')
  const [carrier, setCarrier] = useState<ComboOption | null>(null)
  const [when, setWhen] = useState(toInputDateTime(new Date().toISOString(), tz))
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | undefined>()
  const create = useCreateTransfer(consignmentId)
  const id = (value: string) => (value.trim() === '' ? null : Number(value))

  const submit = () => {
    if (!stopId) {
      setError(t('tracking.needTransferStop'))
      return
    }
    setError(undefined)
    create.mutate(
      {
        transfer_kind: kind,
        to_stop: Number(stopId),
        from_trip: id(fromTrip),
        to_trip: kind === 'to_storage' ? null : id(toTrip),
        to_carrier: kind === 'to_carrier' && !id(toTrip) ? (carrier?.id ?? null) : null,
        transferred_at: fromInputDateTime(when, tz) ?? undefined,
        note: note.trim() || undefined,
      },
      { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }

  return (
    <Dialog
      open
      title={t('tracking.transferTitle')}
      onClose={onClose}
      busy={create.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission="consignments.update" disabled={create.isPending} onClick={submit}>
            {create.isPending ? t('common.saving') : t('tracking.transferSubmit')}
          </WriteButton>
        </>
      }
    >
      <form noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        <FormBanner message={error} />
        {transferStops.length === 0 ? <p className="text-sm text-amber-800 dark:text-amber-200">{t('tracking.noTransferStops')}</p> : null}
        <Select
          label={t('tracking.kind')}
          value={kind}
          options={TRANSFER_KINDS.map((k) => ({ value: k, label: t(`tracking.kinds.${k}`) }))}
          onChange={(v) => { setKind(v as TransferKind) }}
        />
        <Select
          label={t('tracking.stop')}
          value={stopId}
          placeholder={t('tracking.notSelected')}
          options={transferStops.map((s) => ({ value: String(s.id), label: `${String(s.seq)}. ${s.city}` }))}
          onChange={setStopId}
        />
        {kind !== 'from_storage' ? (
          <TextField label={t('tracking.fromTrip')} inputMode="numeric" value={fromTrip} hint={t('tracking.tripOptional')} onChange={(e) => { setFromTrip(e.target.value) }} />
        ) : null}
        {kind !== 'to_storage' ? (
          <TextField label={t('tracking.toTrip')} inputMode="numeric" value={toTrip} hint={t('tracking.tripOptional')} onChange={(e) => { setToTrip(e.target.value) }} />
        ) : null}
        {kind === 'to_carrier' ? (
          <Combobox
            label={t('tracking.toCarrier')}
            queryKey={['carriers', 'search-active']}
            fetchOptions={searchActiveCarriers}
            value={carrier}
            onChange={setCarrier}
          />
        ) : null}
        <DateInput withTime label={t('tracking.transferredAt')} value={when} onChange={setWhen} />
        <TextField label={t('tracking.note')} value={note} onChange={(e) => { setNote(e.target.value) }} />
      </form>
    </Dialog>
  )
}
