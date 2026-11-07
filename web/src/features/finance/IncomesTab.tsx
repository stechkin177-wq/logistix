import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { WriteButton } from '../../shared/ui/WriteButton'
import { FieldsDialog } from './FieldsDialog'
import { useCreateIncome, useIncomeAction, useIncomes } from './ledgerHooks'
import { IncomeStatusBadge } from './LedgerBadges'
import type { IncomeRow, LedgerFilters } from './ledgerTypes'

const SCHEMA = {
  status: codecs.string(''),
  date_from: codecs.date(),
  date_to: codecs.date(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

type Dialog = { kind: 'create' } | { kind: 'deliver' | 'adjust' | 'void'; income: IncomeRow } | null

/** Доходы (engine = new): плановые, признанные, аннулированные; услуги: оказание, подтверждение. */
export function IncomesTab() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const filters: LedgerFilters = { ...state, needs_review: '' }
  const list = useIncomes(filters)
  const action = useIncomeAction()
  const create = useCreateIncome()
  const [dialog, setDialog] = useState<Dialog>(null)
  const close = () => { setDialog(null) }

  const columns: Column<IncomeRow>[] = [
    { key: 'date', header: t('finance.ledger.date'), cell: (i) => <DateTime value={i.recognized_on ?? i.delivered_on ?? ''} dateOnly /> },
    { key: 'order', header: t('finance.operations.order'), cell: (i) => <Link className="text-brand-700 underline dark:text-brand-300" to={`/orders/${String(i.order.id)}`}>{i.order.number}</Link> },
    { key: 'title', header: t('finance.operations.name'), cell: (i) => i.title },
    { key: 'kind', header: t('finance.ledger.kind'), cell: (i) => t(`finance.ledger.incomeKind.${i.kind}`) },
    { key: 'status', header: t('finance.ledger.status'), cell: (i) => <IncomeStatusBadge status={i.status} /> },
    { key: 'amount', header: t('finance.ledger.amount'), align: 'right', cell: (i) => <Money value={i.amount} currency={i.currency?.code} /> },
    { key: 'base', header: t('finance.ledger.baseAmount'), align: 'right', cell: (i) => (i.base_amount ? <Money value={i.base_amount} /> : '—') },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      cell: (i) => (
        <div className="flex flex-wrap gap-1">
          {i.kind === 'service' && i.status === 'planned' ? (
            <>
              <WriteButton permission="finance.update" onClick={() => { setDialog({ kind: 'deliver', income: i }) }}>{t('finance.ledger.deliver')}</WriteButton>
              {i.delivered_on ? (
                <WriteButton permission="finance.update" disabled={action.isPending} onClick={() => { action.mutate({ id: i.id, action: 'confirm', body: {} }) }}>
                  {t('finance.ledger.confirm')}
                </WriteButton>
              ) : null}
            </>
          ) : null}
          {i.status === 'recognized' ? (
            <WriteButton permission="finance.update" onClick={() => { setDialog({ kind: 'adjust', income: i }) }}>{t('finance.ledger.adjust')}</WriteButton>
          ) : null}
          {i.status === 'planned' ? (
            <WriteButton permission="finance.delete" onClick={() => { setDialog({ kind: 'void', income: i }) }}>{t('finance.ledger.void')}</WriteButton>
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
            options={(['planned', 'recognized', 'void'] as const).map((s) => ({ value: s, label: t(`finance.ledger.incomeStatus.${s}`) }))}
          />
          <DateInput label={t('finance.operations.from')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
          <DateInput label={t('finance.operations.to')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
        </div>
        <WriteButton variant="primary" permission="finance.create" onClick={() => { setDialog({ kind: 'create' }) }}>{t('finance.ledger.newService')}</WriteButton>
      </div>
      {action.isError ? <p role="alert" className="text-sm text-red-600">{errorMessage(action.error, t)}</p> : null}
      <DataTable
        caption={t('finance.tabs.incomes')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(i) => i.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('finance.ledger.noIncomes')} />}
      />
      {list.data ? <Pagination page={state.page} pageSize={state.pageSize} count={list.data.count} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize, page: 1 }) }} /> : null}
      {dialog?.kind === 'create' ? (
        <FieldsDialog
          title={t('finance.ledger.newService')}
          submitLabel={t('common.create')}
          permission="finance.create"
          onClose={close}
          fields={[
            { key: 'order', label: t('finance.ledger.orderId'), type: 'decimal', required: true },
            { key: 'title', label: t('finance.operations.name'), required: true },
            { key: 'category', label: t('finance.operations.category') },
            { key: 'amount', label: t('finance.ledger.amount'), type: 'decimal', required: true },
          ]}
          onSubmit={(v) => create.mutateAsync({ order: Number(v.order), title: v.title ?? '', category: v.category, amount: (v.amount ?? '').trim() })}
        />
      ) : null}
      {dialog?.kind === 'deliver' ? (
        <FieldsDialog
          title={t('finance.ledger.deliver')}
          submitLabel={t('finance.ledger.deliver')}
          permission="finance.update"
          onClose={close}
          fields={[
            { key: 'delivered_on', label: t('finance.ledger.deliveredOn'), type: 'date', required: true },
            ...(hasPermission('finance.adjust_closed') ? [{ key: 'adjust_reason', label: t('finance.ledger.adjustReason') }] : []),
          ]}
          onSubmit={(v) => action.mutateAsync({ id: dialog.income.id, action: 'deliver', body: v })}
        />
      ) : null}
      {dialog?.kind === 'adjust' ? (
        <FieldsDialog
          title={t('finance.ledger.adjust')}
          submitLabel={t('finance.ledger.adjust')}
          permission="finance.update"
          hint={t('finance.ledger.adjustHint')}
          onClose={close}
          fields={[
            { key: 'new_amount', label: t('finance.ledger.newAmount'), type: 'decimal', required: true, initial: dialog.income.amount },
            { key: 'reason', label: t('finance.ledger.reason'), required: true },
          ]}
          onSubmit={(v) => action.mutateAsync({ id: dialog.income.id, action: 'adjust', body: { new_amount: (v.new_amount ?? '').trim(), reason: v.reason } })}
        />
      ) : null}
      {dialog?.kind === 'void' ? (
        <FieldsDialog
          title={t('finance.ledger.void')}
          submitLabel={t('finance.ledger.void')}
          permission="finance.delete"
          onClose={close}
          fields={[{ key: 'reason', label: t('finance.ledger.reason'), required: true }]}
          onSubmit={(v) => action.mutateAsync({ id: dialog.income.id, action: 'void', body: { reason: v.reason } })}
        />
      ) : null}
    </div>
  )
}
