import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { errorMessage } from '../../../shared/api/errors'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { DateTime } from '../../../shared/ui/DateTime'
import { Money } from '../../../shared/ui/Money'
import { PAGE_SIZES, Pagination } from '../../../shared/ui/Pagination'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { PartyDrawer } from '../components/PartyDrawer'
import { useDeleteParty, usePartyList } from '../hooks'
import type { Carrier, Client, Party, PartyKind } from '../types'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Building2, Truck } from '../../../shared/ui/icons'

const ORDERINGS = {
  clients: ['name', '-name', 'created_at', '-created_at'],
  carriers: ['name', '-name', 'created_at', '-created_at', 'rating', '-rating'],
} as const

function schemaFor(kind: PartyKind) {
  return {
    q: codecs.string(''),
    type: codecs.id(),
    status: codecs.oneOf(['', 'active', 'inactive'] as const, ''),
    ordering: codecs.oneOf(ORDERINGS[kind], 'name'),
    page: codecs.positiveInt(1),
    pageSize: codecs.choiceInt(PAGE_SIZES, 50),
  }
}
const SCHEMAS = { clients: schemaFor('clients'), carriers: schemaFor('carriers') }

/** Список клиентов или перевозчиков: поиск, фильтры, сортировка, страницы, правка в Drawer, мягкое удаление. */
export function PartyListPage({ kind }: { kind: PartyKind }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const navigate = useNavigate()
  const [state, setState] = useUrlState(SCHEMAS[kind], { pageKey: 'page' })
  const list = usePartyList(kind, state)
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const types = useHandbookValues(kind === 'clients' ? 'client_type' : 'carrier_type')
  const remove = useDeleteParty(kind)
  const canCreate = useCanWrite(`${kind}.create`)
  const [editor, setEditor] = useState<{ party: Party | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Party | null>(null)
  const filtered = state.q !== '' || state.type !== null || state.status !== ''

  const columns: Column<Party>[] = [
    {
      key: 'name',
      header: t('parties.name'),
      sortKey: 'name',
      cell: (p) => (
        <Link to={`/${kind}/${String(p.id)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">
          {p.name}
        </Link>
      ),
    },
    { key: 'bin', header: t('parties.binIin'), cell: (p) => p.bin_iin || '—' },
    { key: 'type', header: t('parties.type'), cell: (p) => p.type_name ?? '—' },
    {
      key: 'status',
      header: t('common.status'),
      cell: (p) => <Badge tone={p.status === 'active' ? 'success' : 'neutral'}>{t(p.status === 'active' ? 'common.active' : 'common.inactive')}</Badge>,
    },
    ...(kind === 'clients'
      ? ([
          { key: 'credit', header: t('parties.creditLimit'), align: 'right', cell: (p: Party) => <Money value={(p as Client).credit_limit} /> },
          {
            key: 'orders',
            header: t('parties.ordersCount'),
            align: 'right',
            cell: (p: Party) => (
              <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/orders?client=${p.id}`}>
                {(p as Client).orders_count}
              </Link>
            ),
          },
        ] satisfies Column<Party>[])
      : ([
          { key: 'rating', header: t('parties.rating'), sortKey: 'rating', align: 'right', cell: (p: Party) => (p as Carrier).rating ?? '—' },
        ] satisfies Column<Party>[])),
    { key: 'created', header: t('parties.created'), sortKey: 'created_at', cell: (p) => <DateTime value={p.created_at} dateOnly /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (p) =>
        hasPermission(`${kind}.delete`) ? (
          <WriteButton
            permission={`${kind}.delete`}
            variant="ghost"
            aria-label={t('parties.deleteNamed', { name: p.name })}
            onClick={() => { setToDelete(p) }}
          >
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]

  const confirmDelete = () => {
    if (!toDelete) return
    remove.mutate(toDelete.id, {
      onSuccess: () => { setToDelete(null) },
    })
  }

  return (
    <div className="space-y-3">
      <PageHeader icon={(kind === 'clients' ? Building2 : Truck)} title={t(`nav.${kind}`)}
        actions={
          <>
            <WriteButton permission={`${kind}.create`} variant="primary" onClick={() => { setEditor({ party: null, nonce: Date.now() }) }}>
              {t(`parties.${kind}.new`)}
            </WriteButton>
          </>
        }
      />
      <FilterBar
        canReset={filtered}
        onReset={() => { setState({ q: '', type: null, status: '' }) }}
      >
        <FilterItem className="w-56">
          <TextField label={t('common.search')} type="search" placeholder={t('parties.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('parties.type')}
            value={state.type === null ? '' : String(state.type)}
            placeholder={t('common.all')}
            options={types.values.map((v) => ({ value: String(v.id), label: v.name }))}
            onChange={(v) => { setState({ type: v ? Number(v) : null }) }}
          />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('common.status')}
            value={state.status}
            placeholder={t('common.all')}
            options={[
              { value: 'active', label: t('common.active') },
              { value: 'inactive', label: t('common.inactive') },
            ]}
            onChange={(v) => { setState({ status: v === 'active' || v === 'inactive' ? v : '' }) }}
          />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t(`nav.${kind}`)}
        columns={columns}
        rows={list.data?.results}
        rowKey={(p) => p.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        ordering={state.ordering}
        onOrderingChange={(ordering) => { setState({ ordering: ordering as typeof state.ordering }) }}
        empty={
          filtered ? (
            <EmptyState title={t('common.noResults')} hint={t('parties.tryOtherFilters')}>
              <Button onClick={() => { setState({ q: '', type: null, status: '' }) }}>{t('common.reset')}</Button>
            </EmptyState>
          ) : (
            <EmptyState title={t(`parties.${kind}.empty`)} hint={t(`parties.${kind}.emptyHint`)}>
              {canCreate ? (
                <Button variant="primary" onClick={() => { setEditor({ party: null, nonce: Date.now() }) }}>
                  {t(`parties.${kind}.new`)}
                </Button>
              ) : null}
            </EmptyState>
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
      {editor ? (
        <PartyDrawer
          key={editor.nonce}
          kind={kind}
          party={editor.party}
          open
          onClose={() => { setEditor(null) }}
          onSaved={(saved) => { void navigate(`/${kind}/${String(saved.id)}`) }}
        />
      ) : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t(`parties.${kind}.deleteTitle`)}
        message={t(`parties.${kind}.deleteMessage`, { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={confirmDelete}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </div>
  )
}
