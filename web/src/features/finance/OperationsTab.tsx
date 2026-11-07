import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { safeFilename } from '../../shared/api/filename'
import { saveBlob } from '../../shared/api/saveBlob'
import { useFormat } from '../../shared/format/useFormat'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { ExcludedHint } from '../../shared/ui/ExcludedHint'
import { Money } from '../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { TextField } from '../../shared/ui/TextField'
import { exportOperations } from './api'
import { useOperations } from './hooks'
import type { OperationRow, OperationsFilters } from './types'

const SCHEMA = {
  date_from: codecs.date(),
  date_to: codecs.date(),
  category: codecs.string(''),
  client: codecs.id(),
  order: codecs.id(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

export function OperationsTab() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const filters: OperationsFilters = state
  const list = useOperations(filters)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const download = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await exportOperations(filters)
      saveBlob(blob, safeFilename(filename, 'operations.xlsx'))
    } catch (error) {
      setExportError(error instanceof ApiError && error.status === 400 && error.detail ? error.detail : errorMessage(error, t))
    } finally {
      setExporting(false)
    }
  }

  const columns: Column<OperationRow>[] = [
    { key: 'date', header: t('finance.operations.date'), cell: (o) => <DateTime value={o.date} dateOnly /> },
    { key: 'order', header: t('finance.operations.order'), cell: (o) => <Link className="text-brand-700 underline dark:text-brand-300" to={`/orders/${String(o.order.id)}`}>{o.order.number}</Link> },
    { key: 'client', header: t('finance.operations.client'), cell: (o) => o.client.name },
    { key: 'title', header: t('finance.operations.name'), cell: (o) => (
      <>
        {o.title}
        {o.base_status === 'prior_base' || o.base_status === 'no_rate' ? (
          <span className="ml-1 text-xs text-amber-700 dark:text-amber-300">({t(o.base_status === 'prior_base' ? 'finance.excluded.rowPriorBase' : 'finance.excluded.rowNoRate')})</span>
        ) : null}
      </>
    ) },
    { key: 'category', header: t('finance.operations.category'), cell: (o) => o.category || '—' },
    { key: 'income', header: t('finance.operations.income'), align: 'right', cell: (o) => <Money value={o.income} currency={o.currency} /> },
    { key: 'expense', header: t('finance.operations.expense'), align: 'right', cell: (o) => <Money value={o.expense} currency={o.currency} /> },
  ]
  const summary = list.data?.summary

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <DateInput label={t('finance.operations.from')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
          <DateInput label={t('finance.operations.to')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
          <TextField label={t('finance.operations.categoryFilter')} value={state.category} onChange={(e) => { setState({ category: e.target.value }) }} />
        </div>
        <Button onClick={() => { void download() }} disabled={exporting}>
          {exporting ? t('finance.operations.exporting') : t('finance.operations.export')}
        </Button>
      </div>
      {exportError ? <Banner kind="error">{exportError}</Banner> : null}
      {summary ? (
        <div role="group" aria-label={t('finance.operations.summary')} className="grid gap-2 sm:grid-cols-3">
          {([
            ['incomeKzt', summary.income_kzt],
            ['expenseKzt', summary.expense_kzt],
            ['diffKzt', summary.diff_kzt],
          ] as const).map(([key, value]) => (
            <div key={key} className="rounded border border-slate-200 p-2 dark:border-slate-700">
              <p className="text-xs text-slate-500">{t(`finance.operations.${key}`, { currency: summary.currency ?? 'KZT' })}</p>
              <p className="text-lg font-semibold tabular-nums">{money(value)}</p>
            </div>
          ))}
          <ul className="text-xs text-slate-600 sm:col-span-3 dark:text-slate-300" aria-label={t('finance.operations.byCurrency')}>
            {Object.entries(summary.by_currency).map(([code, v]) => (
              <li key={code}>{code}: {money(v.income)} / {money(v.expense)} → {money(v.diff)}</li>
            ))}
          </ul>
          <ExcludedHint excluded={summary.excluded} className="text-xs text-amber-700 sm:col-span-3 dark:text-amber-300" />
          {summary.unconverted > 0 ? <p className="text-xs text-amber-700 sm:col-span-3 dark:text-amber-300">{t('finance.operations.unconverted', { count: summary.unconverted })}</p> : null}
        </div>
      ) : null}
      <DataTable
        caption={t('finance.operations.title')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(o) => o.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('finance.operations.empty')} hint={t('finance.operations.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
