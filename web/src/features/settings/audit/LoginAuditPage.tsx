import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import type { AuditEntry } from '../../../shared/entity/EntityHistory'
import { usePageFallback } from '../../../shared/hooks/usePageFallback'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateInput } from '../../../shared/ui/DateInput'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { KeyRound } from '../../../shared/ui/icons'
import { PAGE_SIZES, Pagination, type Paginated } from '../../../shared/ui/Pagination'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Select } from '../../../shared/ui/Select'
import { useUsers, userLabel } from '../../../shared/users/useUsers'

const SCHEMA = {
  event: codecs.oneOf(['', 'login', 'login_failed'] as const, ''),
  from: codecs.date(),
  to: codecs.date(),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

/** Аудит входов: успешные входы, переходы между компаниями и неудачные попытки (право audit.view). */
export function LoginAuditPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const { users } = useUsers()
  const list = useQuery({
    queryKey: ['audit', 'logins', state],
    queryFn: ({ signal }) =>
      api.get<Paginated<AuditEntry>>(
        '/audit/',
        {
          actions: state.event || 'login,login_failed',
          created_from: state.from || undefined,
          created_to: state.to || undefined,
          page: state.page,
          page_size: state.pageSize,
        },
        { signal },
      ),
  })
  usePageFallback(list.error, state.page, () => { setState({ page: 1 }) })
  const who = (id: number | null) => {
    const user = id === null ? undefined : users.find((u) => u.user_id === id)
    return user ? userLabel(user) : t('audit.unknownUser')
  }
  const filtered = state.event !== '' || state.from !== '' || state.to !== ''
  const reset = () => { setState({ event: '', from: '', to: '' }) }

  const columns: Column<AuditEntry>[] = [
    { key: 'when', header: t('audit.when'), cell: (e) => <DateTime value={e.created_at} /> },
    { key: 'who', header: t('audit.who'), cell: (e) => who(e.user) },
    {
      key: 'event',
      header: t('audit.event'),
      cell: (e) => (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <Badge tone={e.action === 'login' ? 'success' : 'danger'}>{t(`audit.${e.action}`)}</Badge>
          {e.changes.switched_to !== undefined ? <span className="text-xs text-muted">{t('audit.switched')}</span> : null}
        </span>
      ),
    },
    { key: 'ip', header: t('audit.ip'), cell: (e) => <span className="tabular-nums">{e.ip ?? '—'}</span> },
    {
      key: 'device',
      header: t('audit.device'),
      cell: (e) => {
        const agent = typeof e.changes.user_agent === 'string' ? e.changes.user_agent : ''
        return <span className="block max-w-xs truncate" title={agent}>{agent || '—'}</span>
      },
    },
    {
      key: 'reason',
      header: t('audit.reason'),
      cell: (e) => {
        const reason = e.changes.reason
        return typeof reason === 'string' ? t(`audit.reasons.${reason}`, { defaultValue: reason }) : '—'
      },
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader icon={KeyRound} title={t('audit.title')} subtitle={t('audit.intro')} />
      <FilterBar canReset={filtered} onReset={reset}>
        <FilterItem>
          <Select
            label={t('audit.event')}
            value={state.event}
            placeholder={t('audit.allEvents')}
            options={[{ value: 'login', label: t('audit.login') }, { value: 'login_failed', label: t('audit.login_failed') }]}
            onChange={(v) => { setState({ event: v === 'login' || v === 'login_failed' ? v : '', page: 1 }) }}
          />
        </FilterItem>
        <FilterItem><DateInput label={t('audit.from')} value={state.from} onChange={(v) => { setState({ from: v, page: 1 }) }} /></FilterItem>
        <FilterItem><DateInput label={t('audit.to')} value={state.to} onChange={(v) => { setState({ to: v, page: 1 }) }} /></FilterItem>
      </FilterBar>
      <DataTable
        caption={t('audit.title')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(e) => e.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState icon={KeyRound} title={t('audit.empty')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
    </div>
  )
}
