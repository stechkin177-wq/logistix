import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { EntityHistory } from '../../../shared/entity/EntityHistory'
import { useFormat } from '../../../shared/format/useFormat'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Card, CardBody, CardHeader } from '../../../shared/ui/Card'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { Boxes, FileText, History, MapPin, Route, Trash2, Wallet } from '../../../shared/ui/icons'
import { Money } from '../../../shared/ui/Money'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Spinner } from '../../../shared/ui/Spinner'
import { Tabs, type TabDef } from '../../../shared/ui/Tabs'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { useFinanceEngine } from '../../finance/ledgerHooks'
import { TripFinanceBlock } from '../../finance/TripFinanceBlock'
import { useCurrencies } from '../../orders/hooks'
import { ReassignDrawer } from '../components/ReassignDrawer'
import { TripLegs } from '../components/TripLegs'
import { TripMainForm } from '../components/TripMainForm'
import { TripStatusControl } from '../components/TripStatusControl'
import { useDeleteTrip, useTrip } from '../hooks'
import type { Trip } from '../types'

const TABS = ['main', 'cargo', 'route', 'finance', 'history'] as const
const SCHEMA = { tab: codecs.oneOf(TABS, 'main') }

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-medium">{children}</dd>
    </div>
  )
}

function Summary({ trip }: { trip: Trip }) {
  const { t } = useTranslation()
  const { codeOf } = useCurrencies()
  return (
    <Card>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 p-4 sm:grid-cols-3 lg:grid-cols-5">
        <Fact label={t('trips.carrier')}>
          {trip.carrier !== null && trip.carrier_name ? (
            <Link to={`/carriers/${String(trip.carrier)}`} className="text-brand-700 hover:underline dark:text-brand-300">{trip.carrier_name}</Link>
          ) : (
            <Badge tone="warning">{t('orders.noCarrier')}</Badge>
          )}
        </Fact>
        <Fact label={t('trips.vehicleDriver')}>{[trip.vehicle_plate, trip.driver_name].filter(Boolean).join(' / ') || '—'}</Fact>
        <Fact label={t('trips.orders')}>
          <span className="flex flex-wrap gap-x-2">
            {trip.orders.length === 0 ? '—' : trip.orders.map((o) => (
              <Link key={o.id} to={`/orders/${String(o.id)}`} className="text-brand-700 hover:underline dark:text-brand-300">{o.number}</Link>
            ))}
          </span>
        </Fact>
        <Fact label={t('trips.summaryComposition')}>
          {t('trips.summaryCompositionValue', { cargo: trip.consignments.length, legs: (trip.legs ?? []).length })}
        </Fact>
        <Fact label={t('trips.carrierPrice')}><Money value={trip.carrier_price} currency={codeOf(trip.currency) || undefined} /></Fact>
      </dl>
    </Card>
  )
}

function Content({ trip }: { trip: Trip }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { dateTime } = useFormat()
  const { hasPermission, hasModule } = useSession()
  const { engine } = useFinanceEngine()
  const remove = useDeleteTrip()
  const [state, setState] = useUrlState(SCHEMA)
  const [reassigning, setReassigning] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const canFinance = hasPermission('finance.view') && hasModule('finance')
  const tabs: TabDef[] = [
    { key: 'main', label: t('trips.tabMain'), icon: Route },
    { key: 'cargo', label: t('trips.tabCargo'), icon: Boxes, count: trip.consignments.length },
    { key: 'route', label: t('trips.tabRoute'), icon: MapPin, count: (trip.legs ?? []).length },
    ...(canFinance ? [{ key: 'finance', label: t('trips.tabFinance'), icon: Wallet }] : []),
    { key: 'history', label: t('trips.tabHistory'), icon: History },
  ]
  const active = tabs.some((x) => x.key === state.tab) ? state.tab : 'main'

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ to: '/trips', label: t('nav.trips') }}
        title={trip.number}
        meta={
          <>
            <TripStatusControl trip={trip} />
            {trip.is_consolidated ? <Badge tone="info">{t('trips.consolidatedShort')}</Badge> : null}
            {trip.completed_at ? <span className="text-xs text-muted">{t('trips.completedAt')}: {dateTime(trip.completed_at)}</span> : null}
          </>
        }
        actions={
          <>
            {trip.carrier !== null ? (
              <IssueDocumentButton kind="carrier_order" source={{ trip: trip.id }} label={t('documents.kind.carrier_order')} />
            ) : null}
            <IssueDocumentButton kind="cmr" source={{ trip: trip.id }} label={t('documents.kind.cmr')} />
            {hasPermission('trips.delete') ? (
              <WriteButton permission="trips.delete" variant="danger" icon={Trash2} onClick={() => { setDeleting(true) }}>{t('trips.delete')}</WriteButton>
            ) : null}
          </>
        }
      />
      <Summary trip={trip} />
      <Tabs tabs={tabs} active={active} label={t('trips.tabs')} onChange={(tab) => { setState({ tab: TABS.find((x) => x === tab) ?? 'main' }, { replace: true }) }} />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {active === 'main' ? (
          <Card><CardBody><TripMainForm key={`${String(trip.id)}-${trip.carrier_price}-${String(trip.carrier)}`} trip={trip} /></CardBody></Card>
        ) : null}
        {active === 'cargo' ? (
          <Card>
            <CardHeader title={t('trips.cargo')} actions={<WriteButton permission="trips.update" onClick={() => { setReassigning(true) }}>{t('trips.changeCargo')}</WriteButton>} />
            {trip.consignments.length === 0 ? (
              <EmptyState icon={Boxes} title={t('trips.noCargo')} />
            ) : (
              <ul className="divide-y divide-line text-sm">
                {trip.consignments.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3">
                    <span className="font-medium">{c.name}</span>
                    <Link to={`/orders/${String(c.order)}`} className="text-brand-700 hover:underline dark:text-brand-300">{c.order_number}</Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ) : null}
        {active === 'route' ? (
          (trip.legs ?? []).length === 0 ? (
            <Card><EmptyState icon={MapPin} title={t('trips.noLegs')} hint={t('trips.noLegsHint')} /></Card>
          ) : (
            <TripLegs legs={trip.legs ?? []} />
          )
        ) : null}
        {active === 'finance' ? (
          engine === 'new' ? (
            <TripFinanceBlock tripId={trip.id} />
          ) : (
            <Banner kind="info">
              <span className="inline-flex items-center gap-1.5"><FileText className="size-4" aria-hidden="true" />{t('trips.financeLegacyHint')}</span>
            </Banner>
          )
        ) : null}
        {active === 'history' ? <EntityHistory objectType="forwarding.trip" objectId={trip.id} /> : null}
      </div>
      {reassigning ? <ReassignDrawer trip={trip} onClose={() => { setReassigning(false) }} /> : null}
      <ConfirmDialog
        open={deleting}
        danger
        title={t('trips.deleteTitle')}
        message={t('trips.deleteMessage', { number: trip.number })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { remove.mutate(trip.id, { onSuccess: () => void navigate('/trips', { replace: true }) }) }}
        onCancel={() => { setDeleting(false); remove.reset() }}
      />
    </div>
  )
}

/** Страница рейса: сводка, вкладки Основное / Грузы / Маршрут / Финансы / История. */
export function TripDetailPage() {
  const { t } = useTranslation()
  const params = useParams()
  const rawId = params.id ?? ''
  const id = /^\d{1,12}$/.test(rawId) ? Number(rawId) : null
  const query = useTrip(id)

  if (id === null || (query.isError && query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <EmptyState icon={Route} title={t('trips.notFound')}>
        <Link to="/trips" className="text-sm text-brand-700 hover:underline dark:text-brand-300">{t('nav.trips')}</Link>
      </EmptyState>
    )
  }
  if (query.isError) {
    return (
      <div className="space-y-2">
        <Banner kind="error">{errorMessage(query.error, t)}</Banner>
        <Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!query.data) return <Spinner label={t('common.loading')} />
  return <Content trip={query.data} />
}
