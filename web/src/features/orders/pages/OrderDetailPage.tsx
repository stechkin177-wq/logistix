import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { Spinner } from '../../../shared/ui/Spinner'
import { Tabs, type TabDef } from '../../../shared/ui/Tabs'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { CreateTripButton } from '../components/CreateTripButton'
import { CargoTab } from '../components/CargoTab'
import { FinanceTab } from '../components/FinanceTab'
import { HistoryTab } from '../components/HistoryTab'
import { OverviewTab } from '../components/OverviewTab'
import { StatusControl } from '../components/StatusControl'
import { TripsTab } from '../components/TripsTab'
import { useDeleteOrder, useOrder } from '../hooks'

const TABS = ['overview', 'cargo', 'finance', 'trips', 'history'] as const
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

  const tabs: TabDef[] = [
    { key: 'overview', label: t('orders.tabOverview') },
    { key: 'cargo', label: t('orders.tabCargo') },
    ...(hasPermission('finance.view') && hasModule('finance') ? [{ key: 'finance', label: t('orders.tabFinance') }] : []),
    ...(hasPermission('trips.view') ? [{ key: 'trips', label: t('orders.tabTrips') }] : []),
    { key: 'history', label: t('orders.tabHistory') },
  ]
  const active = tabs.some((x) => x.key === state.tab) ? state.tab : 'overview'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link to="/orders" className="text-sm text-brand-700 hover:underline dark:text-brand-300">← {t('nav.orders')}</Link>
        <h1 className="text-base font-semibold">{order.number}</h1>
        <StatusControl orderId={order.id} number={order.number} statusId={order.status} statusName={order.status_name} />
        <Link to={`/clients?q=${encodeURIComponent(order.client_name)}`} className="text-sm text-brand-700 hover:underline dark:text-brand-300">
          {order.client_name}
        </Link>
        <span className="ml-auto flex flex-wrap gap-2">
          <CreateTripButton order={order} />
          <IssueDocumentButton kind="order_request" source={{ order: order.id }} label={t('documents.kind.order_request')} />
        </span>
        {hasPermission('orders.delete') ? (
          <WriteButton variant="danger" permission="orders.delete" onClick={() => { setConfirmDelete(true) }}>
            {t('orders.delete')}
          </WriteButton>
        ) : null}
      </div>
      <Tabs tabs={tabs} active={active} label={t('orders.tabs')} onChange={(tab) => { setState({ tab: TABS.find((x) => x === tab) ?? 'overview' }, { replace: true }) }} />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {active === 'overview' ? <OverviewTab order={order} /> : null}
        {active === 'cargo' ? <CargoTab order={order} /> : null}
        {active === 'finance' ? <FinanceTab order={order} /> : null}
        {active === 'trips' ? <TripsTab order={order} /> : null}
        {active === 'history' ? <HistoryTab order={order} /> : null}
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
