import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Banner } from '../../../shared/ui/Banner'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../../shared/ui/Pagination'
import { Select } from '../../../shared/ui/Select'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { TransferStatusBadge } from '../components/TransferStatusBadge'
import { useConfirmTransfer, useReverseTransfer, useTransferList } from '../hooks'
import { TRANSFER_KINDS, type CargoTransfer } from '../types'

const SCHEMA = {
  status: codecs.string(''),
  kind: codecs.string(''),
  pending: codecs.flag(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Список передач груза: фильтры в адресе, подтверждение и сторно (право consignments.transfer). */
export function TransfersPage() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useTransferList({ consignment: null, ...state })
  const confirm = useConfirmTransfer()
  const reverse = useReverseTransfer()
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const canTransfer = hasPermission('consignments.transfer')
  const failure = confirm.isError ? confirm.error : reverse.isError ? reverse.error : null

  const columns: Column<CargoTransfer>[] = [
    { key: 'cargo', header: t('tracking.cargo'), cell: (x) => <><span className="font-medium">{x.consignment_name}</span>{' '}<Link to={`/orders/${String(x.order)}`} className="text-xs text-brand-700 hover:underline dark:text-brand-300">{x.order_number}</Link></> },
    { key: 'kind', header: t('tracking.kind'), cell: (x) => t(`tracking.kinds.${x.transfer_kind}`) },
    { key: 'stop', header: t('tracking.stop'), cell: (x) => x.to_stop_city },
    { key: 'trips', header: t('tracking.trips'), cell: (x) => [x.from_trip_number, x.to_trip_number].map((n) => n ?? '—').join(' → ') },
    { key: 'carrier', header: t('tracking.carriers'), cell: (x) => `${x.from_carrier_name ?? '—'} → ${x.to_carrier_name ?? '—'}${x.carrier_changed ? ` (${t('tracking.carrierChanged')})` : ''}` },
    { key: 'at', header: t('tracking.transferredAt'), cell: (x) => <DateTime value={x.transferred_at} /> },
    { key: 'status', header: t('tracking.status'), cell: (x) => <TransferStatusBadge transfer={x} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      cell: (x) =>
        canTransfer && x.status !== 'reversed' && x.reversed_by === null ? (
          <span className="flex gap-1">
            {x.status === 'initiated' ? (
              <WriteButton permission="consignments.transfer" disabled={confirm.isPending} onClick={() => { confirm.mutate(x.id) }}>{t('tracking.confirm')}</WriteButton>
            ) : null}
            <WriteButton variant="ghost" permission="consignments.transfer" disabled={reverse.isPending} onClick={() => { reverse.mutate({ id: x.id }) }}>{t('tracking.reverse')}</WriteButton>
          </span>
        ) : null,
    },
  ]

  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t('tracking.transfersTitle')}</h1>
      <FilterBar>
        <FilterItem>
          <Select label={t('tracking.kind')} value={state.kind} placeholder={t('tracking.allKinds')} options={TRANSFER_KINDS.map((k) => ({ value: k, label: t(`tracking.kinds.${k}`) }))} onChange={(kind) => { setState({ kind, page: 1 }) }} />
        </FilterItem>
        <FilterItem>
          <Checkbox label={t('tracking.onlyPending')} checked={state.pending} onChange={(e) => { setState({ pending: e.target.checked, page: 1 }) }} />
        </FilterItem>
      </FilterBar>
      {failure ? <Banner kind="error">{errorMessage(failure, t)}</Banner> : null}
      <DataTable
        caption={t('tracking.transfersTitle')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(x) => x.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('tracking.noTransfers')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
