import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { useHistory } from './hooks'
import type { HistoryRow } from './types'

const SCHEMA = {
  kind: codecs.oneOf(['', 'plan', 'subscription'] as const, ''),
  key: codecs.string(''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

const short = (v: unknown) => {
  const text = typeof v === 'string' ? v : JSON.stringify(v)
  return text.length > 80 ? `${text.slice(0, 77)}…` : text
}

/** Журнал изменений тарифов и подписок: кто, когда, что изменено (было → стало). */
export function HistoryPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useHistory(state.kind, state.key, state.page, state.pageSize)

  const columns: Column<HistoryRow>[] = [
    { key: 'when', header: t('platform.history.when'), cell: (e) => <DateTime value={e.created_at} /> },
    { key: 'who', header: t('platform.history.who'), cell: (e) => e.actor || '—' },
    { key: 'object', header: t('platform.history.object'), cell: (e) => `${t(`platform.history.kind.${e.kind}`)}: ${e.key}` },
    { key: 'action', header: t('platform.history.action'), cell: (e) => t(`platform.history.actions.${e.action}`, { defaultValue: e.action }) },
    {
      key: 'changes',
      header: t('platform.history.changes'),
      cell: (e) => (
        <ul className="space-y-0.5 text-xs">
          {Object.entries(e.changes).map(([field, value]) => (
            <li key={field}>
              <b>{field}</b>:{' '}
              {Array.isArray(value) && value.length === 2 ? `${short(value[0])} → ${short(value[1])}` : short(value)}
            </li>
          ))}
        </ul>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.platformHistory')}</h1>
      <FilterBar canReset={state.kind !== '' || state.key !== ''} onReset={() => { setState({ kind: '', key: '' }) }}>
        <FilterItem>
          <Select
            label={t('platform.history.object')}
            value={state.kind}
            placeholder={t('common.all')}
            options={[{ value: 'plan', label: t('platform.history.kind.plan') }, { value: 'subscription', label: t('platform.history.kind.subscription') }]}
            onChange={(v) => { setState({ kind: v === 'plan' || v === 'subscription' ? v : '' }) }}
          />
        </FilterItem>
        <FilterItem className="w-56">
          <TextField label={t('platform.history.key')} placeholder={t('platform.history.keyHint')} value={state.key} onChange={(e) => { setState({ key: e.target.value }, { replace: true }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('nav.platformHistory')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(e) => e.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('platform.history.empty')} hint={t('platform.history.emptyHint')} />}
      />
      <Pagination
        page={state.page}
        pageSize={state.pageSize}
        count={list.data?.count ?? 0}
        onPage={(page) => { setState({ page }) }}
        onPageSize={(pageSize) => { setState({ pageSize }) }}
      />
    </div>
  )
}
