import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { EntityHistory } from '../../../shared/entity/EntityHistory'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { Boxes, FileText, History, Paperclip, Route, Trash2, Wallet } from '../../../shared/ui/icons'
import { SubjectLabels } from '../../labels/SubjectLabels'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Spinner } from '../../../shared/ui/Spinner'
import { Tabs, type TabDef } from '../../../shared/ui/Tabs'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { EntityDocuments } from '../../documents/EntityDocuments'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { OrderSummary } from '../components/OrderSummary'
import { CreateTripButton } from '../components/CreateTripButton'
import { CargoTab } from '../components/CargoTab'
import { FinanceTab } from '../components/FinanceTab'
import { HistoryTab } from '../components/HistoryTab'
import { OverviewTab } from '../components/OverviewTab'
import { StatusControl } from '../components/StatusControl'
import { TripsTab } from '../components/TripsTab'
import { useDeleteOrder, useOrder, useTripsOfOrder } from '../hooks'

const TABS = ['overview', 'cargo', 'finance', 'trips', 'documents', 'history'] as const
const SCHEMA = { tab: codecs.oneOf(TABS, 'overview') }

export function OrderDetailPage() {
  const { t } = useTranslation()
  const params = useParams()
  const navigate = useNavigate()
  const { hasPermission, hasModule } = useSession()
  const rawId = params.id ?? ''
  const id = /^\d{1,12}$/.test(rawId) ? Number(rawId) : null
  const query = useOrder(id)
  const remove = useDeleteOrder()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [state, setState] = useUrlState(SCHEMA)
  // те же рейсы использует вкладка «Рейсы» (общий ключ запроса): сводка не добавляет лишнего запроса
  const tripsQuery = useTripsOfOrder({ id: id ?? 0, number: query.data?.number ?? '' }, hasPermission('trips.view') && query.data !== undefined)
  const trips = tripsQuery.data ?? []

  if (id === null || (query.isError && query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <EmptyState title={t('orders.notFound')}>
        <Link to="/orders" className="text-sm text-brand-700 hover:underline dark:text-brand-300">{t('nav.orders')}</Link>
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
  const order = query.data
  if (!order) return <Spinner label={t('common.loading')} />

  const canFinance = hasPermission('finance.view') && hasModule('finance')
  const canTrips = hasPermission('trips.view')
  const canDocs = hasModule('documents') && hasPermission('documents.view')
  const tabs: TabDef[] = [
    { key: 'overview', label: t('orders.tabOverview'), icon: FileText },
    { key: 'cargo', label: t('orders.tabCargo'), icon: Boxes, count: order.consignments.length },
    ...(canTrips ? [{ key: 'trips', label: t('orders.tabTrips'), icon: Route, count: trips.length }] : []),
    ...(canFinance ? [{ key: 'finance', label: t('orders.tabFinance'), icon: Wallet }] : []),
    ...(canDocs ? [{ key: 'documents', label: t('orders.tabDocuments'), icon: Paperclip }] : []),
    { key: 'history', label: t('orders.tabHistory'), icon: History, count: (order.history ?? []).length },
  ]
  const active = tabs.some((x) => x.key === state.tab) ? state.tab : 'overview'

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ to: '/orders', label: t('nav.orders') }}
        title={order.number}
        meta={
          <>
            <StatusControl orderId={order.id} number={order.number} statusId={order.status} statusName={order.status_name} />
            <SubjectLabels kind="order" id={order.id} labels={order.labels} />
            <Link to={`/clients/${String(order.client)}`} className="text-sm text-brand-700 hover:underline dark:text-brand-300">
              {order.client_name}
            </Link>
          </>
        }
        actions={
          <>
            <CreateTripButton order={order} />
            <IssueDocumentButton kind="order_request" source={{ order: order.id }} label={t('documents.kind.order_request')} />
            {hasPermission('orders.delete') ? (
              <WriteButton variant="danger" permission="orders.delete" icon={Trash2} onClick={() => { setConfirmDelete(true) }}>
                {t('orders.delete')}
              </WriteButton>
            ) : null}
          </>
        }
      />
      <OrderSummary order={order} trips={trips} showMargin={canFinance} />
      <Tabs tabs={tabs} active={active} label={t('orders.tabs')} onChange={(tab) => { setState({ tab: TABS.find((x) => x === tab) ?? 'overview' }, { replace: true }) }} />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {active === 'overview' ? <OverviewTab order={order} /> : null}
        {active === 'cargo' ? <CargoTab order={order} /> : null}
        {active === 'finance' ? <FinanceTab order={order} /> : null}
        {active === 'trips' ? <TripsTab order={order} /> : null}
        {active === 'documents' ? <EntityDocuments source={{ order: order.id }} actions={<IssueDocumentButton kind="order_request" source={{ order: order.id }} label={t('documents.kind.order_request')} />} /> : null}
        {active === 'history' ? (
          <div className="space-y-4">
            <HistoryTab order={order} />
            <EntityHistory objectType="forwarding.order" objectId={order.id} />
          </div>
        ) : null}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        danger
        title={t('orders.deleteTitle')}
        message={t('orders.deleteMessage', { number: order.number })}
        confirmLabel={t('orders.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setConfirmDelete(false); remove.reset() }}
        onConfirm={() => { remove.mutate(order.id, { onSuccess: () => void navigate('/orders') }) }}
      />
    </div>
  )
}
