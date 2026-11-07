import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { WriteButton } from '../../shared/ui/WriteButton'
import { RealizedExcludedHint } from './DebtsExcludedHint'
import { useDeletePayment, usePayments } from './hooks'
import type { Payment } from './types'

const SCHEMA = {
  direction: codecs.oneOf(['', 'out', 'in'] as const, ''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

export function PaymentsTab() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = usePayments(state.page, state.pageSize, state.direction)
  const remove = useDeletePayment()
  const [toDelete, setToDelete] = useState<Payment | null>(null)
  const summary = list.data?.summary // только в новой модели учёта
  const base = summary?.base_currency

  const columns: Column<Payment>[] = [
    { key: 'date', header: t('finance.payments.date'), cell: (p) => <DateTime value={p.date} dateOnly /> },
    {
      key: 'invoice',
      header: t('finance.payments.invoice'),
      cell: (p) => (
        <Link className="text-brand-700 underline dark:text-brand-300" to={`/finance/invoices/${String(p.invoice.id)}`}>
          {p.invoice.number || t('finance.invoices.draftNo', { id: p.invoice.id })}
        </Link>
      ),
    },
    { key: 'direction', header: t('finance.invoices.direction'), cell: (p) => t(`finance.direction.${p.invoice.direction}`) },
    { key: 'amount', header: t('finance.payments.amount'), align: 'right', cell: (p) => <Money value={p.amount} /> },
    { key: 'method', header: t('finance.payments.method'), cell: (p) => t(`finance.payments.methods.${p.method}`) },
    { key: 'ref', header: t('finance.payments.ref'), cell: (p) => p.payment_ref || '—' },
    base
      ? {
          key: 'fx',
          header: t('finance.fx.realized', { currency: base }),
          align: 'right',
          cell: (p) =>
            p.fx_realized_base == null ? (
              <span title={t(`finance.fx.status.${p.fx_status ?? 'no_base_rate'}`)}>—</span>
            ) : (
              <span title={t('finance.fx.paymentRateTip', { invoice: p.invoice_rate_to_base ?? '', payment: p.rate_to_base ?? '' })}>
                <Money value={p.fx_realized_base} currency={base} />
              </span>
            ),
        }
      : { key: 'fx', header: t('finance.payments.fx'), align: 'right', cell: (p) => <Money value={p.fx_difference_kzt} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (p) =>
        hasPermission('finance.delete') ? (
          <WriteButton variant="ghost" permission="finance.delete" aria-label={t('finance.payments.deleteNamed', { date: p.date })} onClick={() => { setToDelete(p) }}>
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]

  return (
    <div className="space-y-3">
      <Select
        label={t('finance.invoices.direction')}
        value={state.direction}
        placeholder={t('finance.invoices.allDirections')}
        options={[{ value: 'out', label: t('finance.direction.out') }, { value: 'in', label: t('finance.direction.in') }]}
        onChange={(value) => { setState({ direction: value as typeof state.direction }) }}
      />
      {summary ? (
        <div role="group" aria-label={t('finance.fx.realizedTitle')} className="rounded border border-slate-200 p-2 dark:border-slate-700">
          <p className="text-xs text-slate-500">{t('finance.fx.realizedTotal', { currency: summary.base_currency })}</p>
          <p className="text-lg font-semibold tabular-nums"><Money value={summary.fx_realized_base} currency={summary.base_currency} /></p>
          <RealizedExcludedHint summary={summary} />
        </div>
      ) : null}
      <DataTable
        caption={t('finance.tabs.payments')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(p) => p.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('finance.payments.empty')} hint={t('finance.payments.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('finance.payments.deleteTitle')}
        message={toDelete ? t('finance.payments.deleteMessage', { amount: toDelete.amount, date: toDelete.date }) : ''}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
