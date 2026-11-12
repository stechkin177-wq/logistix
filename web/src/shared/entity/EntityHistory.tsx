import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { errorMessage } from '../api/errors'
import { useSession } from '../auth/useSession'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { DateTime } from '../ui/DateTime'
import { EmptyState } from '../ui/EmptyState'
import { History, Pencil, Plus, RotateCcw, Trash2, type LucideIcon } from '../ui/icons'
import { Pagination, type Paginated } from '../ui/Pagination'
import { Spinner } from '../ui/Spinner'
import { useUsers, userLabel } from '../users/useUsers'

/** Запись журнала аудита (GET /api/audit/): та же, что видна в настройках компании. */
export interface AuditEntry {
  id: number
  user: number | null
  action: 'create' | 'update' | 'delete' | 'restore' | 'login'
  object_type: string
  object_id: string
  object_repr: string
  changes: Record<string, unknown>
  changes_labels: Record<string, string>
  created_at: string
}

const PAGE_SIZE = 20
const ICONS: Record<AuditEntry['action'], LucideIcon> = {
  create: Plus, update: Pencil, delete: Trash2, restore: RotateCcw, login: History,
}

/** Значение поля словами: пусто - тире, да/нет, остальное как есть. */
export function formatChangeValue(value: unknown, t: (key: string) => string): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? t('common.yes') : t('common.no')
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  return JSON.stringify(value)
}

function ChangeList({ entry }: { entry: AuditEntry }) {
  const { t } = useTranslation()
  const rows = Object.entries(entry.changes)
  if (rows.length === 0) return null
  if (entry.action === 'create') {
    return <p className="mt-1 text-xs text-muted">{t('entity.filledFields', { count: rows.length })}</p>
  }
  return (
    <ul className="mt-1 space-y-0.5 text-xs">
      {rows.map(([key, value]) => {
        const pair = Array.isArray(value) && value.length === 2 ? value : null
        return (
          <li key={key} className="flex flex-wrap gap-x-1.5">
            <span className="text-muted">{entry.changes_labels[key] ?? key}:</span>
            {pair ? (
              <span>
                <span className="text-muted line-through decoration-slate-300">{formatChangeValue(pair[0], t)}</span>
                {' → '}
                <span className="font-medium">{formatChangeValue(pair[1], t)}</span>
              </span>
            ) : (
              <span className="font-medium">{formatChangeValue(value, t)}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

interface Props {
  /** Тип объекта журнала: метка модели Django в нижнем регистре, например forwarding.trip. */
  objectType: string
  objectId: number | string
}

/**
 * Сквозная история записи: кто, когда и что изменил. Источник - существующий журнал аудита
 * (чтение, право company.view); отдельного хранилища истории нет.
 */
export function EntityHistory({ objectType, objectId }: Props) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const { users } = useUsers()
  const allowed = hasPermission('company.view')
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: ['audit', 'entity', objectType, String(objectId), page],
    queryFn: ({ signal }) =>
      api.get<Paginated<AuditEntry>>('/audit/', { object_type: objectType, object_id: String(objectId), page, page_size: PAGE_SIZE }, { signal }),
    enabled: allowed,
  })
  const who = (id: number | null) => {
    const user = id === null ? undefined : users.find((u) => u.user_id === id)
    return user ? userLabel(user) : t('entity.systemUser')
  }

  if (!allowed) return <EmptyState icon={History} title={t('entity.historyNoAccess')} hint={t('entity.historyNoAccessHint')} />
  if (query.isError) {
    return (
      <div className="space-y-2">
        <Banner kind="error">{errorMessage(query.error, t)}</Banner>
        <Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!query.data) return <Spinner label={t('common.loading')} />
  if (query.data.results.length === 0) return <EmptyState icon={History} title={t('entity.historyEmpty')} />

  return (
    <div className="space-y-2">
      <Card>
        <ol aria-label={t('entity.history')} className="divide-y divide-line">
          {query.data.results.map((entry) => {
            const Icon = ICONS[entry.action]
            return (
              <li key={entry.id} className="flex gap-3 px-4 py-3">
                <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted">
                  <Icon className="size-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    <span className="font-medium">{t(`entity.actions.${entry.action}`)}</span>
                    <span className="text-muted"> · {who(entry.user)} · </span>
                    <DateTime value={entry.created_at} />
                  </p>
                  <ChangeList entry={entry} />
                </div>
              </li>
            )
          })}
        </ol>
      </Card>
      <Pagination page={page} pageSize={PAGE_SIZE} count={query.data.count} onPage={setPage} />
    </div>
  )
}
