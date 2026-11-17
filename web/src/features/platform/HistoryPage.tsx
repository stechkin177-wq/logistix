import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { useHistory } from './hooks'
import { ManageHeader } from './ManageHeader'

const TONE: Record<string, 'neutral' | 'success' | 'warning' | 'danger' | 'info'> = {
  create: 'success', publish: 'success', renew: 'success', unblock: 'success', restore: 'success',
  delete: 'danger', block: 'danger', login_failed: 'danger', totp_failed: 'danger',
  archive: 'warning', unpublish: 'warning',
  update: 'info', change_plan: 'info', set_default: 'info',
}

const SCHEMA = {
  kind: codecs.oneOf(['', 'plan', 'subscription', 'auth', 'company'] as const, ''),
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
  const list = useHistory(state.kind, state.key.trim(), state.page, state.pageSize)
  const rows = list.data?.results ?? []
  // статусы в изменениях показываем словами, а не кодами; неизвестные значения остаются как есть
  const shown = (field: string, v: unknown) => {
    if (field === 'status' && typeof v === 'string') {
      return t(`company.statuses.${v}`, { defaultValue: t(`platform.plans.status.${v}`, { defaultValue: v }) })
    }
    return short(v)
  }

  return (
    <div className="space-y-3">
      <ManageHeader active="history" />
      <FilterBar
        search={<FilterItem className="w-auto"> <TextField label={t('platform.history.key')} type="search" placeholder={t('platform.history.keyHint')} value={state.key} onChange={(e) => { setState({ key: e.target.value }, { replace: true }) }} /> </FilterItem>}
        canReset={state.kind !== '' || state.key !== ''}
        onReset={() => { setState({ kind: '', key: '' }) }}
      >
        <FilterItem>
          <Select
            label={t('platform.history.object')}
            value={state.kind}
            placeholder={t('common.all')}
            options={(['plan', 'subscription', 'company', 'auth'] as const).map((k) => ({ value: k, label: t(`platform.history.kind.${k}`) }))}
            onChange={(v) => { setState({ kind: v === 'plan' || v === 'subscription' || v === 'auth' || v === 'company' ? v : '' }) }}
          />
        </FilterItem>
      </FilterBar>
      {list.isError ? (
        <Banner kind="error">{errorMessage(list.error, t)} <Button onClick={() => void list.refetch()}>{t('common.retry')}</Button></Banner>
      ) : rows.length === 0 && !list.isFetching ? (
        <EmptyState title={t('platform.history.empty')} hint={t('platform.history.emptyHint')} />
      ) : (
        <ul aria-label={t('nav.platformHistory')} className="space-y-2">
          {rows.map((e) => {
            const companyId = e.kind === 'subscription' || e.kind === 'company' ? e.key : null
            return (
              <li key={e.id} className="rounded-card border border-line bg-surface px-3 py-2.5 shadow-card">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Badge tone={TONE[e.action] ?? 'neutral'}>{t(`platform.history.actions.${e.action}`, { defaultValue: e.action })}</Badge>
                  <span className="text-sm font-medium text-ink">
                    {t(`platform.history.kind.${e.kind}`)}
                    {companyId === null && e.key !== '*' ? <span className="font-normal text-muted">: {e.key}</span> : null}
                  </span>
                </div>
                <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                  <dt className="text-muted">{t('platform.history.when')}</dt>
                  <dd className="text-ink"><DateTime value={e.created_at} /></dd>
                  <dt className="text-muted">{t('platform.history.who')}</dt>
                  <dd className="min-w-0 break-words text-ink">{e.actor || '—'}</dd>
                  {companyId !== null ? (
                    <>
                      <dt className="text-muted">{t('platform.history.companyId')}</dt>
                      <dd className="text-ink">{companyId}</dd>
                    </>
                  ) : null}
                </dl>
                {Object.keys(e.changes).length > 0 ? (
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries(e.changes).map(([field, value]) => (
                      <li key={field} className="max-w-full rounded-control bg-surface-2 px-2 py-0.5 text-xs text-ink">
                        <span className="text-muted">{t(`platform.history.fields.${field}`, { defaultValue: field })}:</span>{' '}
                        {Array.isArray(value) && value.length === 2 ? `${shown(field, value[0])} → ${shown(field, value[1])}` : shown(field, value)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
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
