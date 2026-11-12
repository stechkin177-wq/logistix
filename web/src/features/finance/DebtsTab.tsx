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
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { Select } from '../../shared/ui/Select'
import { exportDebts } from './api'
import { DebtsExcludedHint } from './DebtsExcludedHint'
import { useDebts } from './hooks'
import type { AppliedRate, DebtRow } from './types'

const SCHEMA = { kind: codecs.oneOf(['clients', 'carriers'] as const, 'clients') }

/** Остатки по валютам: «USD 100,00; KZT 50,00». */
function perCurrency(map: Record<string, string> | undefined, money: (v: string) => string) {
  const entries = Object.entries(map ?? {})
  return entries.length === 0 ? '—' : entries.map(([code, v]) => `${code} ${money(v)}`).join('; ')
}

export function DebtsTab() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const [state, setState] = useUrlState(SCHEMA)
  const isClients = state.kind === 'clients'
  const debts = useDebts(state.kind)
  const base = debts.data?.base_currency // есть только в новой модели учёта
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const download = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await exportDebts(state.kind)
      saveBlob(blob, safeFilename(filename, 'debts.xlsx'))
    } catch (error) {
      setExportError(error instanceof ApiError && error.detail ? error.detail : errorMessage(error, t))
    } finally {
      setExporting(false)
    }
  }
  /** Подсказка к эквиваленту: применённый курс, его дата и источник по каждой валюте. */
  const rateTip = (rates: Record<string, AppliedRate> | undefined) =>
    Object.entries(rates ?? {})
      .map(([code, r]) => t('finance.fx.rateTip', { code, base: base ?? '', rate: money(r.rate), date: r.rate_date, source: t(`finance.fx.source.${r.source}`) }))
      .join('\n')

  const nameColumn: Column<DebtRow> = {
      key: 'name',
      header: t('finance.debts.name'),
      cell: (d) => (
        <Link className="text-brand-700 underline dark:text-brand-300" title={t('finance.debts.openInvoices', { name: d.name })} to={`/finance?tab=invoices&${isClients ? 'client' : 'carrier'}=${String(d.id)}`}>
          {d.name}
        </Link>
      ),
  }
  const limitColumns: Column<DebtRow>[] = isClients
    ? [
        { key: 'limit', header: t('finance.debts.limit'), align: 'right' as const, cell: (d: DebtRow) => (Number(d.credit_limit ?? 0) > 0 ? <Money value={d.credit_limit} /> : t('finance.debts.noLimit')) },
        { key: 'usage', header: t('finance.debts.usage'), align: 'right' as const, cell: (d: DebtRow) => (d.limit_usage_pct == null ? '—' : `${money(d.limit_usage_pct)} %`) },
      ]
    : []

  // новая модель: исходная сумма + эквивалент в базе (курс на дату отчёта - в подсказке);
  // курсовая разница нереализованная - отдельной колонкой, без сложения с реализованной
  const baseColumns: Column<DebtRow>[] = [
    nameColumn,
    { key: 'balance', header: t('finance.fx.balanceOriginal'), cell: (d) => perCurrency(d.balance, money) },
    {
      key: 'balanceBase',
      header: t('finance.fx.balanceBase', { currency: base }),
      align: 'right',
      cell: (d) => <span title={rateTip(d.applied_rate)}><Money value={d.balance_base} currency={base} /></span>,
    },
    { key: 'overdueOriginal', header: t('finance.fx.overdueOriginal'), cell: (d) => perCurrency(d.overdue, money) },
    { key: 'overdueBase', header: t('finance.fx.overdueBase', { currency: base }), align: 'right', cell: (d) => <Money value={d.overdue_base} currency={base} /> },
    { key: 'carrying', header: t('finance.fx.carrying', { currency: base }), align: 'right', cell: (d) => <Money value={d.carrying_base} currency={base} /> },
    { key: 'unrealized', header: t('finance.fx.unrealized', { currency: base }), align: 'right', cell: (d) => <Money value={d.unrealized_diff} currency={base} /> },
    ...limitColumns,
  ]

  const legacyColumns: Column<DebtRow>[] = [
    nameColumn,
    { key: 'issued', header: t('finance.debts.issued'), align: 'right', cell: (d) => <Money value={d.issued_kzt} /> },
    { key: 'paid', header: t('finance.debts.paid'), align: 'right', cell: (d) => <Money value={d.paid_kzt} /> },
    { key: 'balance', header: t('finance.debts.balance'), align: 'right', cell: (d) => <Money value={d.balance_kzt} /> },
    { key: 'overdue', header: t('finance.debts.overdue'), align: 'right', cell: (d) => <Money value={d.overdue_kzt} /> },
    {
      key: 'currency',
      header: t('finance.debts.byCurrency'),
      cell: (d) => Object.entries(d.by_currency).map(([code, v]) => `${code} ${money(v.balance)}`).join('; '),
    },
    ...limitColumns,
  ]
  const columns = base ? baseColumns : legacyColumns

  return (
    <div className="space-y-3">
      <Select
        label={t('finance.debts.kind')}
        value={state.kind}
        options={[{ value: 'clients', label: t('finance.debts.clients') }, { value: 'carriers', label: t('finance.debts.carriers') }]}
        onChange={(value) => { setState({ kind: value as typeof state.kind }) }}
      />
      {base ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">
            {t('finance.fx.asOf', { date: debts.data?.as_of ?? '', currency: base })}
          </p>
          <Button onClick={() => { void download() }} disabled={exporting}>
            {exporting ? t('finance.operations.exporting') : t('finance.operations.export')}
          </Button>
        </div>
      ) : null}
      {exportError ? <Banner kind="error">{exportError}</Banner> : null}
      {base ? <DebtsExcludedHint excluded={debts.data?.excluded} /> : null}
      <DataTable
        caption={t('finance.tabs.debts')}
        columns={columns}
        rows={debts.data?.results}
        rowKey={(d) => d.id}
        loading={debts.isPending}
        error={debts.isError ? errorMessage(debts.error, t) : undefined}
        onRetry={() => { void debts.refetch() }}
        empty={<EmptyState title={t('finance.debts.empty')} hint={t('finance.debts.emptyHint')} />}
      />
    </div>
  )
}
