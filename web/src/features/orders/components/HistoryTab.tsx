import { useTranslation } from 'react-i18next'
import { useUsers, userLabel } from '../../../shared/users/useUsers'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import type { Order, OrderHistoryEntry } from '../types'

export function HistoryTab({ order }: { order: Order }) {
  const { t } = useTranslation()
  const { users } = useUsers()
  const who = (id: number | null) => {
    if (id === null) return '—'
    const user = users.find((u) => u.user_id === id)
    return user ? userLabel(user) : '—'
  }
  const columns: Column<OrderHistoryEntry>[] = [
    { key: 'when', header: t('orders.historyWhen'), cell: (h) => <DateTime value={h.created_at} /> },
    { key: 'from', header: t('orders.historyFrom'), cell: (h) => h.from_status_name ?? '—' },
    { key: 'to', header: t('orders.historyTo'), cell: (h) => h.to_status_name },
    { key: 'who', header: t('orders.historyWho'), cell: (h) => who(h.user) },
  ]
  return (
    <DataTable
      caption={t('orders.tabHistory')}
      columns={columns}
      rows={order.history ?? []}
      rowKey={(h) => h.id}
      empty={<EmptyState title={t('orders.noHistory')} />}
    />
  )
}
