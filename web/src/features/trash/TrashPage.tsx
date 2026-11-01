import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../shared/api/client'
import { errorMessage } from '../../shared/api/errors'
import { usePageFallback } from '../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Button } from '../../shared/ui/Button'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination, type Paginated } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { pushToast } from '../../shared/ui/toast'
import { WriteButton } from '../../shared/ui/WriteButton'

export const TRASH_CODES = ['clients', 'carriers', 'orders', 'consignments', 'trips'] as const

interface TrashEntry {
  code: string
  id: number
  label: string
  deleted_at: string
}

const SCHEMA = {
  code: codecs.oneOf(['', ...TRASH_CODES] as const, ''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Тип объекта корзины: известные коды - через i18n, незнакомый показывается как есть. */
function useTypeLabel() {
  const { t, i18n } = useTranslation()
  return (code: string) => (i18n.exists(`trash.types.${code}`) ? t(`trash.types.${code}`) : code)
}

/** Корзина: удалённые объекты по типам, восстановление (trash.update + право типа проверяет сервер). */
export function TrashPage() {
  const { t } = useTranslation()
  const typeLabel = useTypeLabel()
  const qc = useQueryClient()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useQuery({
    queryKey: ['trash', 'list', state],
    queryFn: ({ signal }) =>
      api.get<Paginated<TrashEntry>>('/trash/', { code: state.code, page: state.page, page_size: state.pageSize }, { signal }),
    placeholderData: keepPreviousData,
  })
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })

  const restore = useMutation({
    mutationFn: (entry: TrashEntry) => api.post<{ code: string; id: number; label: string }>(`/trash/${entry.code}/${String(entry.id)}/restore/`),
    onSuccess: async (_, entry) => {
      pushToast('info', t('trash.restored', { label: entry.label || `#${String(entry.id)}` }))
      // восстановленный объект возвращается в свои списки
      await Promise.all(
        ['trash', entry.code, 'dashboard', 'orders', 'consignments', 'trips'].map((key) => qc.invalidateQueries({ queryKey: [key] })),
      )
    },
    // 409 (конфликт / blocker) - текст сервера как есть; 404 - уже восстановлен или удалён навсегда
    onError: async (error) => {
      pushToast('error', errorMessage(error, t))
      await qc.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  const columns: Column<TrashEntry>[] = [
    { key: 'type', header: t('trash.type'), cell: (e) => typeLabel(e.code) },
    { key: 'label', header: t('trash.object'), cell: (e) => <span className="font-medium">{e.label || `#${String(e.id)}`}</span> },
    { key: 'deleted', header: t('trash.deletedAt'), cell: (e) => <DateTime value={e.deleted_at} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (e) => (
        <WriteButton
          permission="trash.update"
          aria-label={t('trash.restoreNamed', { label: e.label || `#${String(e.id)}` })}
          disabled={restore.isPending}
          onClick={() => { restore.mutate(e) }}
        >
          {t('trash.restore')}
        </WriteButton>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.trash')}</h1>
      <FilterBar canReset={state.code !== ''} onReset={() => { setState({ code: '' }) }}>
        <FilterItem className="w-52">
          <Select
            label={t('trash.type')}
            value={state.code}
            placeholder={t('common.all')}
            options={TRASH_CODES.map((c) => ({ value: c, label: typeLabel(c) }))}
            onChange={(v) => { setState({ code: TRASH_CODES.find((c) => c === v) ?? '' }) }}
          />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('nav.trash')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(e) => `${e.code}:${String(e.id)}`}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={
          state.code !== '' ? (
            <EmptyState title={t('common.noResults')}>
              <Button onClick={() => { setState({ code: '' }) }}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('trash.empty')} hint={t('trash.emptyHint')} />
          )
        }
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
