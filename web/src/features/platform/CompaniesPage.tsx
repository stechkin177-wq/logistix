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
import { useCompanies } from './hooks'
import { SubscriptionDrawer } from './SubscriptionDrawer'
import type { PlatformCompany } from './types'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Landmark } from '../../shared/ui/icons'

const SCHEMA = { q: codecs.string(''), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

/** Администратор платформы: компании и их подписки. */
export function CompaniesPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useCompanies(state.q, state.page, state.pageSize)
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
      <PageHeader icon={Landmark} title={t('nav.platformCompanies')} />
      <FilterBar canReset={state.q !== ''} onReset={() => { setState({ q: '' }) }}>
        <FilterItem className="w-64">
          <TextField label={t('common.search')} type="search" placeholder={t('platform.companies.searchPlaceholder')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
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
