import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { useHandbookValues } from '../../shared/handbooks/useHandbook'
import { Button } from '../../shared/ui/Button'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { WriteButton } from '../../shared/ui/WriteButton'
import { FieldsDialog } from './FieldsDialog'
import { useCreateExpense, useExpenses, useVoidExpense } from './ledgerHooks'
import { ExpenseStatusBadge, ReviewBadge } from './LedgerBadges'
import type { ExpenseRow, LedgerFilters } from './ledgerTypes'

const SCHEMA = {
  status: codecs.string(''),
  needs_review: codecs.string(''),
  date_from: codecs.date(),
  date_to: codecs.date(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

type Dialog = { kind: 'create' } | { kind: 'void'; expense: ExpenseRow } | null

/** Панель долей: компактный список «заказ/рейс - сумма» + нераспределённый остаток. */
function Allocations({ expense }: { expense: ExpenseRow }) {
  const { t } = useTranslation()
  const cur = expense.currency?.code
  return (
    <ul className="space-y-0.5 text-xs" aria-label={t('finance.ledger.allocations')}>
      {expense.allocations.map((a) => (
        <li key={a.id} className="flex gap-2">
          <span>
            {a.order ? <Link className="underline" to={`/orders/${String(a.order.id)}`}>{a.order.number}</Link> : null}
            {a.order && a.trip ? ' / ' : null}
            {a.trip ? a.trip.number : null}
          </span>
          <Money value={a.amount} currency={cur} />
        </li>
      ))}
      {Number(expense.unallocated) > 0 ? (
        <li className="text-slate-500">{t('finance.ledger.unallocated')}: <Money value={expense.unallocated} currency={cur} /></li>
      ) : null}
    </ul>
  )
}

/** Расходы (engine = new): бейдж «нужна проверка», расхождение со счётом, доли по раскрытию. */
export function ExpensesTab() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const filters: LedgerFilters = state
  const list = useExpenses(filters)
  const create = useCreateExpense()
  const voidExpense = useVoidExpense()
  const categories = useHandbookValues('expense_category', { activeOnly: true })
  const currencies = useHandbookValues('currency', { activeOnly: true })
  const [dialog, setDialog] = useState<Dialog>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())
  const toggle = (id: number) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const columns: Column<ExpenseRow>[] = [
    { key: 'date', header: t('finance.ledger.date'), cell: (e) => <DateTime value={e.expense_date} dateOnly /> },
    {
      key: 'title',
      header: t('finance.operations.name'),
      cell: (e) => (
        <div className="space-y-0.5">
          <div>{e.title}</div>
          {open.has(e.id) ? <Allocations expense={e} /> : null}
        </div>
      ),
    },
    { key: 'category', header: t('finance.operations.category'), cell: (e) => e.category.name },
    { key: 'trip', header: t('finance.ledger.trip'), cell: (e) => e.trip?.number ?? '—' },
    {
      key: 'status',
      header: t('finance.ledger.status'),
      cell: (e) => (
        <div className="flex flex-wrap items-center gap-1">
          <ExpenseStatusBadge status={e.status} />
          <ReviewBadge expense={e} />
        </div>
      ),
    },
    { key: 'amount', header: t('finance.ledger.amount'), align: 'right', cell: (e) => <Money value={e.amount} currency={e.currency?.code} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      cell: (e) => (
        <div className="flex flex-wrap gap-1">
          <Button onClick={() => { toggle(e.id) }} aria-expanded={open.has(e.id)}>
            {open.has(e.id) ? t('finance.ledger.hideAllocations') : t('finance.ledger.showAllocations', { count: e.allocations.length })}
          </Button>
          {e.status === 'active' ? (
            <WriteButton permission="finance.delete" onClick={() => { setDialog({ kind: 'void', expense: e }) }}>{t('finance.ledger.void')}</WriteButton>
          ) : null}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label={t('finance.ledger.status')}
            value={state.status}
            onChange={(value) => { setState({ status: value }) }}
            placeholder={t('common.all')}
            options={(['active', 'void'] as const).map((s) => ({ value: s, label: t(`finance.ledger.expenseStatus.${s}`) }))}
          />
          <Select
            label={t('finance.ledger.needsReview')}
            value={state.needs_review}
            onChange={(value) => { setState({ needs_review: value }) }}
            placeholder={t('common.all')}
            options={[{ value: 'true', label: t('finance.ledger.onlyNeedsReview') }]}
          />
          <DateInput label={t('finance.operations.from')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
          <DateInput label={t('finance.operations.to')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
        </div>
        <WriteButton variant="primary" permission="finance.create" onClick={() => { setDialog({ kind: 'create' }) }}>{t('finance.ledger.newExpense')}</WriteButton>
      </div>
      <DataTable
        caption={t('finance.tabs.expenses')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(e) => e.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('finance.ledger.noExpenses')} />}
      />
      {list.data ? <Pagination page={state.page} pageSize={state.pageSize} count={list.data.count} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize, page: 1 }) }} /> : null}
      {dialog?.kind === 'create' ? (
        <FieldsDialog
          title={t('finance.ledger.newExpense')}
          submitLabel={t('common.create')}
          permission="finance.create"
          onClose={() => { setDialog(null) }}
          fields={[
            { key: 'title', label: t('finance.operations.name'), required: true },
            { key: 'category', label: t('finance.operations.category'), type: 'select', required: true, options: categories.values.map((v) => ({ value: String(v.id), label: v.name })) },
            { key: 'amount', label: t('finance.ledger.amount'), type: 'decimal', required: true },
            { key: 'currency', label: t('finance.ledger.currency'), type: 'select', required: true, options: currencies.values.map((v) => ({ value: String(v.id), label: v.code || v.name })) },
            { key: 'expense_date', label: t('finance.ledger.date'), type: 'date', required: true },
          ]}
          onSubmit={(v) =>
            create.mutateAsync({
              title: v.title, category: Number(v.category), amount: (v.amount ?? '').trim(),
              currency: Number(v.currency), expense_date: v.expense_date,
            })
          }
        />
      ) : null}
      {dialog?.kind === 'void' ? (
        <FieldsDialog
          title={t('finance.ledger.void')}
          submitLabel={t('finance.ledger.void')}
          permission="finance.delete"
          onClose={() => { setDialog(null) }}
          fields={[{ key: 'reason', label: t('finance.ledger.reason'), required: true }]}
          onSubmit={(v) => voidExpense.mutateAsync({ id: dialog.expense.id, reason: v.reason ?? '' })}
        />
      ) : null}
    </div>
  )
}
