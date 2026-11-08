import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { serverErrors, NO_ERRORS, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useRef } from 'react'
import { Badge } from '../../../shared/ui/Badge'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DateTime } from '../../../shared/ui/DateTime'
import { Drawer } from '../../../shared/ui/Drawer'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useDeleteConsignment, useSaveConsignment } from '../hooks'
import {
  CONSIGNMENT_KNOWN_PATH, consignmentFromApi, consignmentPayload, emptyConsignment, isMultiStop, validateConsignment, type ConsignmentForm,
} from '../orderForm'
import type { Order, OrderConsignment } from '../types'
import { CargoTracking } from '../../tracking/components/CargoTracking'
import { LocationBadge } from '../../tracking/components/LocationBadge'
import { ConsignmentFields } from './ConsignmentFields'
import { RouteChain } from './RouteChain'
import { RouteLane } from './RouteLane'

function ConsignmentDrawer({ order, consignment, onClose }: { order: Order; consignment: OrderConsignment | null; onClose: () => void }) {
  const { t } = useTranslation()
  const { session } = useSession()
  const tz = session?.company.timezone
  const [form, setForm] = useState<ConsignmentForm>(() => (consignment ? consignmentFromApi(consignment, tz) : emptyConsignment()))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const save = useSaveConsignment()
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const permission = consignment ? 'consignments.update' : 'consignments.create'

  const submit = () => {
    const local: Record<string, string> = {}
    validateConsignment(form, '', t, local)
    // validateConsignment строит пути с ведущей точкой ("." + путь): убираем её
    const fields = Object.fromEntries(Object.entries(local).map(([k, v]) => [k.replace(/^\./, ''), v]))
    if (Object.keys(fields).length > 0) {
      setErrors({ fields, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    const body = { ...consignmentPayload(form, tz), ...(consignment ? {} : { order: order.id }) }
    save.mutate(
      { id: consignment?.id ?? null, body },
      { onSuccess: onClose, onError: (error) => { setErrors(serverErrors(error, t, (p) => CONSIGNMENT_KNOWN_PATH.test(p))) } },
    )
  }

  return (
    <Drawer
      open
      width="max-w-4xl"
      title={consignment ? t('orders.editCargo') : t('orders.addCargo')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission={permission} disabled={save.isPending} onClick={submit}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        <FormBanner message={errors.banner} />
        <ConsignmentFields value={form} onChange={setForm} prefix="" errors={errors.fields} />
      </form>
    </Drawer>
  )
}

export function CargoTab({ order }: { order: Order }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [editor, setEditor] = useState<{ consignment: OrderConsignment | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<OrderConsignment | null>(null)
  const remove = useDeleteConsignment()

  return (
    <div className="space-y-3">
      {hasPermission('consignments.create') ? (
        <WriteButton permission="consignments.create" onClick={() => { setEditor({ consignment: null, nonce: Date.now() }) }}>
          {t('orders.addCargo')}
        </WriteButton>
      ) : null}
      {order.consignments.length === 0 ? (
        <EmptyState title={t('orders.noCargo')} hint={t('orders.noCargoHint')} />
      ) : (
        <ul className="space-y-2">
          {order.consignments.map((c) => (
            <li key={c.id} className="space-y-1 rounded border border-slate-200 bg-white p-2 text-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">{c.name} <Badge>{c.status_name}</Badge> <LocationBadge status={c.location_status} /></p>
                <div className="flex gap-1">
                  {hasPermission('consignments.view') ? (
                    <Button variant="ghost" aria-label={t('orders.editCargoNamed', { name: c.name })} onClick={() => { setEditor({ consignment: c, nonce: Date.now() }) }}>
                      {t('common.edit')}
                    </Button>
                  ) : null}
                  {hasPermission('consignments.delete') ? (
                    <WriteButton variant="ghost" permission="consignments.delete" aria-label={t('orders.deleteCargoNamed', { name: c.name })} onClick={() => { setToDelete(c) }}>
                      {t('common.delete')}
                    </WriteButton>
                  ) : null}
                </div>
              </div>
              <p className="text-xs text-slate-600 dark:text-slate-300">
                {t('orders.cargoSummary', { weight: c.weight_kg, volume: c.volume_m3, pallets: c.pallets, packaging: c.packaging_name ?? '—' })}
              </p>
              {c.route ? <RouteLane route={c.route} /> : c.stops && isMultiStop(c.stops) ? <RouteChain stops={c.stops} /> : null}
              {hasPermission('consignments.view') && c.stops ? <CargoTracking consignmentId={c.id} stops={c.stops} /> : null}
              <ul className="grid gap-1 text-xs md:grid-cols-2">
                {(c.stops && isMultiStop(c.stops) ? c.stops : c.points).map((p, index) => (
                  <li key={'seq' in p ? p.seq : index} className="rounded bg-slate-50 p-1.5 dark:bg-slate-800">
                    <span className="font-medium">{t(`orders.stopKinds.${p.kind}`)}: </span>
                    {[p.country_name, p.city, p.street].filter(Boolean).join(', ')}
                    <br />
                    <DateTime value={p.window_from} />
                    {p.window_to ? <> — <DateTime value={p.window_to} /></> : null}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {editor ? <ConsignmentDrawer key={editor.nonce} order={order} consignment={editor.consignment} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('orders.deleteCargoTitle')}
        message={t('orders.deleteCargoMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => {
          if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } })
        }}
      />
    </div>
  )
}
