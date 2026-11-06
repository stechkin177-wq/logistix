import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Money } from '../../shared/ui/Money'
import { Select } from '../../shared/ui/Select'
import { useDebts } from './hooks'
import type { DebtRow } from './types'

const SCHEMA = { kind: codecs.oneOf(['clients', 'carriers'] as const, 'clients') }

export function DebtsTab() {
  const { t } = useTranslation()
  const { money } = useFormat()
  const [state, setState] = useUrlState(SCHEMA)
  const isClients = state.kind === 'clients'
  const debts = useDebts(state.kind)

  const columns: Column<DebtRow>[] = [
    {
      key: 'name',
      header: t('finance.debts.name'),
      cell: (d) => (
        <Link className="text-brand-700 underline dark:text-brand-300" title={t('finance.debts.openInvoices', { name: d.name })} to={`/finance?tab=invoices&${isClients ? 'client' : 'carrier'}=${String(d.id)}`}>
          {d.name}
        </Link>
      ),
    },
    { key: 'issued', header: t('finance.debts.issued'), align: 'right', cell: (d) => <Money value={d.issued_kzt} /> },
    { key: 'paid', header: t('finance.debts.paid'), align: 'right', cell: (d) => <Money value={d.paid_kzt} /> },
    { key: 'balance', header: t('finance.debts.balance'), align: 'right', cell: (d) => <Money value={d.balance_kzt} /> },
    { key: 'overdue', header: t('finance.debts.overdue'), align: 'right', cell: (d) => <Money value={d.overdue_kzt} /> },
    {
      key: 'currency',
      header: t('finance.debts.byCurrency'),
      cell: (d) => Object.entries(d.by_currency).map(([code, v]) => `${code} ${money(v.balance)}`).join('; '),
    },
    ...(isClients
      ? [
          { key: 'limit', header: t('finance.debts.limit'), align: 'right' as const, cell: (d: DebtRow) => (Number(d.credit_limit ?? 0) > 0 ? <Money value={d.credit_limit} /> : t('finance.debts.noLimit')) },
          { key: 'usage', header: t('finance.debts.usage'), align: 'right' as const, cell: (d: DebtRow) => (d.limit_usage_pct == null ? '—' : `${money(d.limit_usage_pct)} %`) },
        ]
      : []),
  ]

  return (
    <div className="space-y-3">
      <Select
        label={t('finance.debts.kind')}
        value={state.kind}
        options={[{ value: 'clients', label: t('finance.debts.clients') }, { value: 'carriers', label: t('finance.debts.carriers') }]}
        onChange={(value) => { setState({ kind: value as typeof state.kind }) }}
      />
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
