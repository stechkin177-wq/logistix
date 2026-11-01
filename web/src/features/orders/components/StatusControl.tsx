import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { Badge } from '../../../shared/ui/Badge'
import { pushToast } from '../../../shared/ui/toast'
import { useChangeOrderStatus, useOrderStatuses } from '../hooks'

export function statusTone(code: string | undefined, name: string): 'success' | 'danger' | 'info' | 'neutral' {
  if (code === 'completed') return 'success'
  if (code === 'cancelled') return 'danger'
  return name ? 'info' : 'neutral'
}

/**
 * Статус заказа: с правом orders.update - выпадающий список (POST /orders/{id}/status/), иначе значок.
 * Отказ сервера показывается уведомлением, список возвращается к фактическому статусу (после refetch).
 */
export function StatusControl({ orderId, number, statusId, statusName, compact }: {
  orderId: number
  number: string
  statusId: number
  statusName: string
  compact?: boolean
}) {
  const { t } = useTranslation()
  const canUpdate = useCanWrite('orders.update')
  const { statuses } = useOrderStatuses()
  const change = useChangeOrderStatus()
  const current = statuses.find((s) => s.id === statusId)

  if (!canUpdate || statuses.length === 0) {
    return <Badge tone={statusTone(current?.code, statusName)}>{statusName}</Badge>
  }
  const options = statuses.filter((s) => s.isActive || s.id === statusId)
  return (
    <select
      aria-label={t('orders.statusOf', { number })}
      value={statusId}
      disabled={change.isPending}
      onChange={(event) => {
        change.mutate(
          { id: orderId, status: Number(event.target.value) },
          { onError: (error) => { pushToast('error', errorMessage(error, t)) } },
        )
      }}
      className={`rounded border border-slate-300 bg-white text-xs dark:border-slate-600 dark:bg-slate-900 ${compact ? 'h-6 max-w-full px-1' : 'h-7 px-1.5'}`}
    >
      {options.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  )
}
