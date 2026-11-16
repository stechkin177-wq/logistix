import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useInvoices } from './hooks'
import { StatusBadge, invoiceLabel } from './StatusBadge'
import type { Invoice, InvoiceListFilters } from './types'

const STATUSES = ['', 'draft', 'issued', 'partial', 'paid', 'overdue', 'cancelled'] as const
const DIRECTIONS = ['', 'out', 'in'] as const

export const INVOICES_SCHEMA = {
  direction: codecs.oneOf(DIRECTIONS, ''),
  status: codecs.oneOf(STATUSES, ''),
  client: codecs.id(),
  carrier: codecs.id(),
  order: codecs.id(),
  date_from: codecs.date(),
  date_to: codecs.date(),
  search: codecs.string(''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

export function InvoicesTab() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [state, setState] = useUrlState(INVOICES_SCHEMA, { pageKey: 'page' })
  const filters: InvoiceListFilters = state
  const list = useInvoices(filters)
  const hasFilters = Boolean(state.direction || state.status || state.search || state.date_from || state.date_to || state.client || state.carrier || state.order)

  const columns: Column<Invoice>[] = [
    {
      key: 'number',
      className: 'whitespace-nowrap',
      header: t('finance.invoices.number'),
      cell: (i) => <Link className="text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/${String(i.id)}`}>{invoiceLabel(i, t)}</Link>,
    },
    { key: 'direction', className: 'whitespace-nowrap', header: t('finance.invoices.typeShort'), cell: (i) => <Badge tone={i.direction === 'out' ? 'info' : 'neutral'}>{t(`finance.direction.${i.direction}`)}</Badge> },
    { key: 'party', header: t('finance.invoices.party'), cell: (i) => i.client?.name ?? i.carrier?.name ?? '—' },
    { key: 'order', className: 'whitespace-nowrap', header: t('finance.invoices.order'), cell: (i) => i.order?.number ?? i.trip?.number ?? '—' },
    { key: 'issue', className: 'whitespace-nowrap', header: t('finance.invoices.issuedShort'), cell: (i) => (i.issue_date ? <DateTime value={i.issue_date} dateOnly /> : '—') },
    { key: 'due', className: 'whitespace-nowrap', header: t('finance.invoices.dueDate'), cell: (i) => (i.due_date ? <DateTime value={i.due_date} dateOnly /> : '—') },
    { key: 'gross', header: t('finance.invoices.gross'), align: 'right', cell: (i) => (i.status === 'draft' ? '—' : <Money value={i.totals.gross} currency={i.currency.code} />) },
    { key: 'balance', header: t('finance.invoices.balance'), align: 'right', cell: (i) => (i.status === 'draft' ? '—' : <Money value={i.balance} currency={i.currency.code} />) },
    { key: 'status', className: 'whitespace-nowrap', header: t('finance.invoices.status'), cell: (i) => <StatusBadge status={i.display_status} /> },
  ]

  return (
    <div className="space-y-3">
      <FilterBar
        canReset={hasFilters}
        onReset={() => { setState({ direction: '', status: '', search: '', date_from: '', date_to: '', client: null, carrier: null, order: null }) }}
        actions={
          <>
            <WriteButton permission="finance.create" onClick={() => { void navigate('/finance/invoices/new?direction=in') }}>
              {t('finance.invoices.newIn')}
            </WriteButton>
            <WriteButton variant="primary" permission="finance.create" onClick={() => { void navigate('/finance/invoices/new') }}>
              {t('finance.invoices.new')}
            </WriteButton>
          </>
        }
      >
        <FilterItem>
          <Select
            label={t('finance.invoices.direction')}
            value={state.direction}
            placeholder={t('finance.invoices.allDirections')}
            options={DIRECTIONS.filter(Boolean).map((d) => ({ value: d, label: t(`finance.direction.${d}`) }))}
            onChange={(value) => { setState({ direction: value as typeof state.direction }) }}
          />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('finance.invoices.status')}
            value={state.status}
            placeholder={t('finance.invoices.allStatuses')}
            options={STATUSES.filter(Boolean).map((s) => ({ value: s, label: t(`finance.status.${s}`) }))}
            onChange={(value) => { setState({ status: value as typeof state.status }) }}
          />
        </FilterItem>
        <FilterItem className="w-48">
          <TextField label={t('finance.invoices.search')} type="search" value={state.search} onChange={(e) => { setState({ search: e.target.value }) }} />
        </FilterItem>
        <FilterItem>
          <DateInput label={t('finance.invoices.dateFrom')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
        </FilterItem>
        <FilterItem>
          <DateInput label={t('finance.invoices.dateTo')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        fit
        onRowClick={(i) => { void navigate(`/finance/invoices/${String(i.id)}`) }}
        caption={t('finance.tabs.invoices')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(i) => i.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('finance.invoices.empty')} hint={t('finance.invoices.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
