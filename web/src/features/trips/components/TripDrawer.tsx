import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Spinner } from '../../../shared/ui/Spinner'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { useDeleteTrip, usePatchTrip, useTrip } from '../hooks'
import type { Trip } from '../types'
import { ReassignDrawer } from './ReassignDrawer'
import { TripFields, validateTrip, type TripFormState } from './TripFields'
import { TripStatusControl } from './TripStatusControl'

const KNOWN = /^(carrier|vehicle_plate|driver_name|carrier_price|currency)$/

function TripForm({ trip, onClose }: { trip: Trip; onClose: () => void }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const currencies = useHandbookValues('currency')
  const canUpdate = useCanWrite('trips.update')
  const patch = usePatchTrip()
  const remove = useDeleteTrip()
  const formRef = useRef<HTMLFormElement>(null)
  const [form, setForm] = useState<TripFormState>({
    carrier: trip.carrier !== null ? { id: trip.carrier, label: trip.carrier_name ?? `#${String(trip.carrier)}` } : null,
    vehicle_plate: trip.vehicle_plate,
    driver_name: trip.driver_name,
    carrier_price: trip.carrier_price,
    currency: String(trip.currency),
  })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const [reassigning, setReassigning] = useState(false)
  const [deleting, setDeleting] = useState(false)
  useFocusInvalid(formRef, errors)

  const submit = () => {
    const local = validateTrip(form, t)
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    // PATCH несёт только редактируемые поля: номер, статус, грузы и is_consolidated сервер отвергает
    patch.mutate(
      {
        id: trip.id,
        body: {
          carrier: form.carrier?.id ?? null,
          vehicle_plate: form.vehicle_plate.trim(),
          driver_name: form.driver_name.trim(),
          carrier_price: form.carrier_price.trim(),
          ...(form.currency ? { currency: Number(form.currency) } : {}),
        },
      },
      {
        onSuccess: onClose,
        onError: (error) => { setErrors(serverErrors(error, t, (path) => KNOWN.test(path))) },
      },
    )
  }

  return (
    <>
      <form ref={formRef} noValidate className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (canUpdate) submit() }}>
        <FormBanner message={errors.banner} />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold">{trip.number}</span>
          <TripStatusControl trip={trip} />
          {trip.is_consolidated ? <span className="text-xs text-slate-500">{t('trips.consolidated')}</span> : null}
        </div>
        <TripFields
          form={form}
          errors={errors.fields}
          currencies={currencies.values.filter((c) => c.is_active || c.id === trip.currency)}
          disabled={!canUpdate}
          onChange={(key, value) => { setForm((f) => ({ ...f, [key]: value })) }}
        />
        <div className="flex justify-end">
          <WriteButton permission="trips.update" variant="primary" type="submit" disabled={patch.isPending}>
            {patch.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </div>
      </form>
      <section aria-labelledby="trip-cargo" className="mt-4 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <h3 id="trip-cargo" className="text-xs font-medium">{t('trips.cargo')}</h3>
          <WriteButton permission="trips.update" onClick={() => { setReassigning(true) }}>{t('trips.changeCargo')}</WriteButton>
        </div>
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-700">
          {trip.consignments.map((c) => (
            <li key={c.id} className="flex flex-wrap justify-between gap-x-3 px-2 py-1">
              <span>{c.name}</span>
              <Link to={`/orders/${String(c.order)}`} className="text-brand-700 hover:underline dark:text-brand-300">{c.order_number}</Link>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="trip-documents" className="mt-4 space-y-1">
        <h3 id="trip-documents" className="text-xs font-medium">{t('documents.title')}</h3>
        <div className="flex flex-wrap gap-2">
          {trip.carrier !== null ? (
            <IssueDocumentButton kind="carrier_order" source={{ trip: trip.id }} label={t('documents.kind.carrier_order')} />
          ) : null}
          <IssueDocumentButton kind="cmr" source={{ trip: trip.id }} label={t('documents.kind.cmr')} />
        </div>
      </section>
      {hasPermission('trips.delete') ? (
        <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
          <WriteButton permission="trips.delete" variant="danger" onClick={() => { setDeleting(true) }}>{t('trips.delete')}</WriteButton>
        </div>
      ) : null}
      {reassigning ? <ReassignDrawer trip={trip} onClose={() => { setReassigning(false) }} /> : null}
      <ConfirmDialog
        open={deleting}
        danger
        title={t('trips.deleteTitle')}
        message={t('trips.deleteMessage', { number: trip.number })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { remove.mutate(trip.id, { onSuccess: onClose }) }}
        onCancel={() => { setDeleting(false); remove.reset() }}
      />
    </>
  )
}

/** Карточка рейса: правка полей, смена набора грузов, удаление. */
export function TripDrawer({ tripId, onClose }: { tripId: number; onClose: () => void }) {
  const { t } = useTranslation()
  const query = useTrip(tripId)
  return (
    <Drawer open title={t('trips.card')} onClose={onClose}>
      {query.data ? (
        <TripForm key={query.data.id} trip={query.data} onClose={onClose} />
      ) : query.isError ? (
        <div className="space-y-2">
          <Banner kind="error">{errorMessage(query.error, t)}</Banner>
          <Button onClick={() => void query.refetch()}>{t('table.retry')}</Button>
        </div>
      ) : (
        <Spinner label={t('table.loading')} />
      )}
    </Drawer>
  )
}
