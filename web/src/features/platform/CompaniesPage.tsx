import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { TextField } from '../../shared/ui/TextField'
import { useCompanies, usePlans } from './hooks'
import { ManageHeader } from './ManageHeader'
import { Select } from '../../shared/ui/Select'
import { SubscriptionDrawer } from './SubscriptionDrawer'
import type { PlatformCompany } from './types'

const SCHEMA = { q: codecs.string(''), plan: codecs.string(''), state: codecs.oneOf(['', 'active', 'inactive'] as const, ''), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

/** Администратор платформы: компании и их подписки. */
export function CompaniesPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const plans = usePlans()
  const list = useCompanies(state.q, state.plan, state.state, state.page, state.pageSize)
  const [open, setOpen] = useState<{ company: PlatformCompany; nonce: number } | null>(null)

  const columns: Column<PlatformCompany>[] = [
    {
      key: 'name',
      header: t('platform.companies.company'),
      cell: (c) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setOpen({ company: c, nonce: Date.now() }) }}>
          {c.name}
        </button>
      ),
    },
    { key: 'bin', header: t('platform.companies.bin'), cell: (c) => c.bin || '—' },
    { key: 'plan', header: t('platform.companies.plan'), cell: (c) => c.plan_name },
    {
      key: 'status',
      header: t('common.status'),
      cell: (c) => (
        <span className="flex gap-1">
          <Badge tone={c.status === 'active' || c.status === 'trial' ? 'success' : 'warning'}>{t(`company.statuses.${c.status}`)}</Badge>
          {c.is_free_period ? <Badge tone="info">{t('company.freePeriod')}</Badge> : null}
        </span>
      ),
    },
    { key: 'ends', header: t('company.endsAt'), cell: (c) => (c.ends_at ? <DateTime value={c.ends_at} dateOnly /> : t('company.unlimited')) },
  ]

  return (
    <div className="space-y-3">
      <ManageHeader active="companies" />
      <FilterBar
        search={<FilterItem className="w-auto"> <TextField label={t('common.search')} type="search" placeholder={t('platform.companies.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} /> </FilterItem>}
        canReset={state.q !== '' || state.plan !== '' || state.state !== ''}
        onReset={() => { setState({ q: '', plan: '', state: '' }) }}
      >
        <FilterItem>
          <Select
            label={t('platform.companies.filterPlan')}
            value={state.plan}
            placeholder={t('common.all')}
            options={(plans.data ?? []).map((p) => ({ value: p.code, label: p.name }))}
            onChange={(v) => { setState({ plan: v }) }}
          />
        </FilterItem>
        <FilterItem>
          <Select
            label={t('platform.companies.filterState')}
            value={state.state}
            placeholder={t('common.all')}
            options={(['active', 'inactive'] as const).map((k) => ({ value: k, label: t(`platform.companies.states.${k}`) }))}
            onChange={(v) => { setState({ state: v === 'active' || v === 'inactive' ? v : '' }) }}
          />
        </FilterItem>
      </FilterBar>
      <DataTable
        onRowClick={(c) => { setOpen({ company: c, nonce: Date.now() }) }}
        caption={t('nav.platformCompanies')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(c) => c.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('common.noResults')} hint={t('platform.companies.emptyHint')} />}
      />
      <Pagination
        page={state.page}
        pageSize={state.pageSize}
        count={list.data?.count ?? 0}
        onPage={(page) => { setState({ page }) }}
        onPageSize={(pageSize) => { setState({ pageSize }) }}
      />
      {open ? <SubscriptionDrawer key={open.nonce} company={open.company} onClose={() => { setOpen(null) }} /> : null}
    </div>
  )
}
