import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { usePageFallback } from '../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { DriverDrawer } from './DriverDrawer'
import { useDeleteDriver, useDriverList } from './hooks'
import { DRIVER_STATUSES, type Driver } from './types'
import { PageHeader } from '../../shared/ui/PageHeader'
import { UserRound } from '../../shared/ui/icons'

const SCHEMA = {
  q: codecs.string(''),
  status: codecs.oneOf(['', ...DRIVER_STATUSES] as const, ''),
  ordering: codecs.oneOf(['full_name', '-full_name', 'license_expires', '-license_expires'] as const, 'full_name'),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Водители: список с поиском и статусом, карточка в панели справа. */
export function DriversPage() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useDriverList(state)
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const remove = useDeleteDriver()
  const [editor, setEditor] = useState<{ driver: Driver | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Driver | null>(null)
  const filtered = state.q !== '' || state.status !== ''

  const columns: Column<Driver>[] = [
    {
      key: 'name',
      header: t('drivers.fullName'),
      sortKey: 'full_name',
      cell: (d) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ driver: d, nonce: Date.now() }) }}>
          {d.full_name}
        </button>
      ),
    },
    { key: 'phone', header: t('drivers.phone'), cell: (d) => d.phone || '—' },
    { key: 'license', header: t('drivers.license'), cell: (d) => [d.license_number, d.license_categories].filter(Boolean).join(' · ') || '—' },
    { key: 'expires', header: t('drivers.licenseExpires'), sortKey: 'license_expires', cell: (d) => d.license_expires ?? '—' },
    {
      key: 'status',
      header: t('common.status'),
      cell: (d) => <Badge tone={d.status === 'active' ? 'success' : 'neutral'}>{t(`drivers.status.${d.status}`)}</Badge>,
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (d) =>
        hasPermission('drivers.delete') ? (
          <WriteButton permission="drivers.delete" variant="ghost" aria-label={t('drivers.deleteNamed', { name: d.full_name })} onClick={() => { setToDelete(d) }}>
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]

  return (
    <div className="space-y-3">
      <PageHeader icon={UserRound} title={t('nav.drivers')}
        actions={
          <>
            <WriteButton permission="drivers.create" variant="primary" onClick={() => { setEditor({ driver: null, nonce: Date.now() }) }}>
              {t('drivers.new')}
            </WriteButton>
          </>
        }
      />
      <FilterBar canReset={filtered} onReset={() => { setState({ q: '', status: '' }) }}>
        <FilterItem className="w-56">
          <TextField label={t('common.search')} type="search" placeholder={t('drivers.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('common.status')}
            value={state.status}
            placeholder={t('common.all')}
            options={DRIVER_STATUSES.map((s) => ({ value: s, label: t(`drivers.status.${s}`) }))}
            onChange={(v) => { setState({ status: DRIVER_STATUSES.find((s) => s === v) ?? '' }) }}
          />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('nav.drivers')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(d) => d.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        ordering={state.ordering}
        onOrderingChange={(ordering) => { setState({ ordering: ordering as typeof state.ordering }) }}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={() => { setState({ q: '', status: '' }) }}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('drivers.empty')} hint={t('drivers.emptyHint')} />
          )
        }
      />
      <Pagination
        page={state.page}
        pageSize={state.pageSize}
        count={list.data?.count ?? 0}
        onPage={(page) => { setState({ page }) }}
        onPageSize={(pageSize) => { setState({ pageSize }) }}
      />
      {editor ? <DriverDrawer key={editor.nonce} driver={editor.driver} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('drivers.deleteTitle')}
        message={t('drivers.deleteMessage', { name: toDelete?.full_name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
