import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
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

  const columns: Column<Invoice>[] = [
    {
      key: 'number',
      header: t('finance.invoices.number'),
      cell: (i) => <Link className="text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/${String(i.id)}`}>{invoiceLabel(i, t)}</Link>,
    },
    { key: 'direction', header: t('finance.invoices.direction'), cell: (i) => <Badge tone={i.direction === 'out' ? 'info' : 'neutral'}>{t(`finance.direction.${i.direction}`)}</Badge> },
    { key: 'party', header: t('finance.invoices.party'), cell: (i) => i.client?.name ?? i.carrier?.name ?? '—' },
    { key: 'order', header: t('finance.invoices.order'), cell: (i) => i.order?.number ?? i.trip?.number ?? '—' },
    { key: 'issue', header: t('finance.invoices.issueDate'), cell: (i) => (i.issue_date ? <DateTime value={i.issue_date} dateOnly /> : '—') },
    { key: 'due', header: t('finance.invoices.dueDate'), cell: (i) => (i.due_date ? <DateTime value={i.due_date} dateOnly /> : '—') },
    { key: 'gross', header: t('finance.invoices.gross'), align: 'right', cell: (i) => <Money value={i.totals.gross} currency={i.currency.code} /> },
    { key: 'balance', header: t('finance.invoices.balance'), align: 'right', cell: (i) => <Money value={i.balance} currency={i.currency.code} /> },
    { key: 'status', header: t('finance.invoices.status'), cell: (i) => <StatusBadge status={i.display_status} /> },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label={t('finance.invoices.direction')}
            value={state.direction}
            placeholder={t('finance.invoices.allDirections')}
            options={DIRECTIONS.filter(Boolean).map((d) => ({ value: d, label: t(`finance.direction.${d}`) }))}
            onChange={(value) => { setState({ direction: value as typeof state.direction }) }}
          />
          <Select
            label={t('finance.invoices.status')}
            value={state.status}
            placeholder={t('finance.invoices.allStatuses')}
            options={STATUSES.filter(Boolean).map((s) => ({ value: s, label: t(`finance.status.${s}`) }))}
            onChange={(value) => { setState({ status: value as typeof state.status }) }}
          />
          <TextField label={t('finance.invoices.search')} value={state.search} onChange={(e) => { setState({ search: e.target.value }) }} />
          <DateInput label={t('finance.invoices.dateFrom')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
          <DateInput label={t('finance.invoices.dateTo')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
        </div>
        <div className="flex gap-2">
          <WriteButton permission="finance.create" onClick={() => { void navigate('/finance/invoices/new?direction=in') }}>
            {t('finance.invoices.newIn')}
          </WriteButton>
          <WriteButton variant="primary" permission="finance.create" onClick={() => { void navigate('/finance/invoices/new') }}>
            {t('finance.invoices.new')}
          </WriteButton>
        </div>
      </div>
      <DataTable
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
