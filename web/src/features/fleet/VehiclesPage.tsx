import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
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
import { useDeleteVehicle, useReminders, useVehicleList } from './hooks'
import { SELECTABLE_KINDS, VEHICLE_KINDS, VEHICLE_STATUSES, type Reminder, type Vehicle } from './types'
import { VehicleDrawer } from './VehicleDrawer'
import { PageHeader } from '../../shared/ui/PageHeader'
import { CarFront, TriangleAlert, Plus } from '../../shared/ui/icons'

const SCHEMA = {
  q: codecs.string(''),
  kind: codecs.oneOf(['', ...VEHICLE_KINDS] as const, ''),
  status: codecs.oneOf(['', ...VEHICLE_STATUSES] as const, ''),
  ordering: codecs.oneOf(['plate', '-plate', 'year', '-year'] as const, 'plate'),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Автопарк: список техники, предупреждения (ТО, документы, страховки) и единая карточка в панели. */
export function VehiclesPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useVehicleList(state)
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const reminders = useReminders()
  const remove = useDeleteVehicle()
  const [editor, setEditor] = useState<{ vehicle: Vehicle | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Vehicle | null>(null)
  const filtered = state.q !== '' || state.kind !== '' || state.status !== ''

  const byVehicle = useMemo(() => {
    const map = new Map<number, Reminder[]>()
    for (const r of reminders.data?.results ?? []) map.set(r.vehicle, [...(map.get(r.vehicle) ?? []), r])
    return map
  }, [reminders.data])

  const columns: Column<Vehicle>[] = [
    {
      key: 'plate',
      header: t('fleet.plate'),
      sortKey: 'plate',
      cell: (v) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ vehicle: v, nonce: Date.now() }) }}>
          {v.plate}
        </button>
      ),
    },
    { key: 'kind', header: t('fleet.kind'), cell: (v) => t(`fleet.kinds.${v.kind}`) },
    { key: 'model', header: t('fleet.model'), cell: (v) => [v.make, v.model].filter(Boolean).join(' ') || '—' },
    { key: 'year', header: t('fleet.year'), sortKey: 'year', align: 'right', cell: (v) => v.year ?? '—' },
    {
      key: 'status',
      header: t('common.status'),
      cell: (v) => {
        const items = byVehicle.get(v.id) ?? []
        const overdue = items.some((r) => r.state === 'overdue')
        return (
          <span className="flex flex-wrap gap-1">
            <Badge tone={v.status === 'active' ? 'success' : 'neutral'}>{t(`fleet.status.${v.status}`)}</Badge>
            {items.length > 0 ? <Badge tone={overdue ? 'danger' : 'warning'}>{overdue ? t('fleet.overdue') : t('fleet.dueSoon')}: {items.length}</Badge> : null}
          </span>
        )
      },
    },
  ]

  const warnings = reminders.data?.results ?? []
  return (
    <div className="space-y-3">
      <PageHeader icon={CarFront} title={t('nav.vehicles')} hint="vehicles"
        actions={
          <>
            <WriteButton permission="fleet.create" variant="primary" icon={Plus} onClick={() => { setEditor({ vehicle: null, nonce: Date.now() }) }}>
              {t('fleet.new')}
            </WriteButton>
          </>
        }
      />
      {warnings.length > 0 ? (
        <section aria-label={t('fleet.warnings')} className="overflow-hidden rounded-card border border-amber-300/70 bg-amber-50/70 shadow-card dark:border-amber-700/60 dark:bg-amber-950/40">
          <header className="flex items-center gap-2 border-b border-amber-200/70 px-3 py-2 dark:border-amber-800/50">
            <TriangleAlert className="size-4 text-amber-600 dark:text-amber-400" aria-hidden="true" />
            <h2 className="text-sm font-semibold">{t('fleet.warnings')}</h2>
            <span className="rounded-full bg-amber-200/80 px-2 text-xs font-medium text-amber-900 dark:bg-amber-800/60 dark:text-amber-100">{warnings.length}</span>
          </header>
          <ul className="divide-y divide-amber-200/60 dark:divide-amber-800/40">
            {warnings.slice(0, 8).map((r, i) => (
              <li key={`${String(r.vehicle)}-${String(i)}`}>
                <button type="button" className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 px-3 py-1.5 text-left text-sm hover:bg-amber-100/70 dark:hover:bg-amber-900/30" onClick={() => {
                  const v = list.data?.results.find((x) => x.id === r.vehicle)
                  if (v) setEditor({ vehicle: v, nonce: Date.now() })
                }}>
                  <b className="font-semibold">{r.plate}</b>
                  <span className="text-muted">{r.title}
                    {r.due_date ? ` · ${t('fleet.until')} ${r.due_date}` : ''}
                    {r.due_km != null ? ` · ${String(r.due_km)} ${t('fleet.km')}` : ''}
                  </span>
                  <Badge tone={r.state === 'overdue' ? 'danger' : 'warning'}>{r.state === 'overdue' ? t('fleet.overdue') : t('fleet.dueSoon')}</Badge>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <FilterBar canReset={filtered} onReset={() => { setState({ q: '', kind: '', status: '' }) }}>
        <FilterItem className="w-56">
          <TextField label={t('common.search')} type="search" placeholder={t('fleet.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('common.status')}
            value={state.status}
            placeholder={t('common.all')}
            options={VEHICLE_STATUSES.map((s) => ({ value: s, label: t(`fleet.status.${s}`) }))}
            onChange={(v) => { setState({ status: VEHICLE_STATUSES.find((s) => s === v) ?? '' }) }}
          />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('fleet.kind')}
            value={state.kind}
            placeholder={t('common.all')}
            options={SELECTABLE_KINDS.map((k) => ({ value: k, label: t(`fleet.kinds.${k}`) }))}
            onChange={(v) => { setState({ kind: VEHICLE_KINDS.find((k) => k === v) ?? '' }) }}
          />
        </FilterItem>
      </FilterBar>
      <DataTable
        onRowClick={(v) => { setEditor({ vehicle: v, nonce: Date.now() }) }}
        caption={t('nav.vehicles')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(v) => v.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        ordering={state.ordering}
        onOrderingChange={(ordering) => { setState({ ordering: ordering as typeof state.ordering }) }}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={() => { setState({ q: '', kind: '', status: '' }) }}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t('fleet.empty')} hint={t('fleet.emptyHint')} />
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
      {editor ? <VehicleDrawer key={editor.nonce} vehicle={editor.vehicle} onClose={() => { setEditor(null) }} onDelete={() => { setToDelete(editor.vehicle); setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('fleet.deleteTitle')}
        message={t('fleet.deleteMessage', { name: toDelete?.plate ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
