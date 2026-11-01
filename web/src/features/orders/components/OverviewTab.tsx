import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { useUsers, userLabel } from '../../../shared/users/useUsers'
import { DateTime } from '../../../shared/ui/DateTime'
import { Money } from '../../../shared/ui/Money'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { getParty } from '../../parties/api'
import { useQuery } from '@tanstack/react-query'
import { useCurrencies, useUpdateOrder } from '../hooks'
import type { Order } from '../types'
import { OrderForm } from './OrderForm'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 border-b border-slate-100 py-1 text-sm dark:border-slate-800">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

function useName(code: string, id: number | null) {
  const { all } = useHandbookValues(code)
  return id === null ? '—' : (all.find((v) => v.id === id)?.name ?? '—')
}

export function OverviewTab({ order }: { order: Order }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const update = useUpdateOrder(order.id)
  const canUpdate = useCanWrite('orders.update')
  const { users } = useUsers()
  const { codeOf } = useCurrencies()
  const client = useQuery({
    queryKey: ['clients', 'detail', order.client],
    queryFn: ({ signal }) => getParty('clients', order.client, signal),
    enabled: order.contact !== null,
    staleTime: 60_000,
  })
  const transport = useName('transport_condition', order.transport_condition)
  const delay = useName('payment_delay_condition', order.payment_delay_condition)
  const userName = (id: number | null) => {
    if (id === null) return '—'
    const user = users.find((u) => u.user_id === id)
    return user ? userLabel(user) : id === order.manager ? order.manager_name : `#${String(id)}`
  }
  const contact = order.contact === null ? '—' : (client.data?.contacts.find((c) => c.id === order.contact)?.name ?? '—')

  if (editing) {
    return (
      <OrderForm
        mode="edit"
        order={order}
        submitting={update.isPending}
        error={update.error}
        onSubmit={(body) => { update.mutate(body, { onSuccess: () => { setEditing(false) } }) }}
        onCancel={() => { update.reset(); setEditing(false) }}
      />
    )
  }
  return (
    <div className="space-y-3">
      {canUpdate ? (
        <WriteButton permission="orders.update" onClick={() => { setEditing(true) }}>{t('common.edit')}</WriteButton>
      ) : null}
      <dl className="max-w-3xl">
        <Row label={t('orders.client')}>{order.client_name}</Row>
        <Row label={t('orders.contractNumber')}>{order.contract_number || '—'}</Row>
        <Row label={t('orders.clientRef')}>{order.client_ref || '—'}</Row>
        <Row label={t('orders.contact')}>{contact}</Row>
        <Row label={t('orders.manager')}>{order.manager_name}</Row>
        <Row label={t('orders.forwarder')}>{userName(order.forwarder)}</Row>
        <Row label={t('orders.extraManagers')}>{order.extra_managers.length ? order.extra_managers.map(userName).join(', ') : '—'}</Row>
        <Row label={t('orders.clientRate')}><Money value={order.client_rate} currency={codeOf(order.currency)} /></Row>
        <Row label={t('orders.transportCondition')}>{transport}</Row>
        <Row label={t('orders.deliveryDays')}>{order.delivery_days ?? '—'}</Row>
        <Row label={t('orders.paymentDelayDays')}>{order.payment_delay_days ?? '—'}</Row>
        <Row label={t('orders.paymentDelayCondition')}>{delay}</Row>
        <Row label={t('common.comment')}>{order.comment || '—'}</Row>
        <Row label={t('orders.route')}>{order.route || '—'}</Row>
        <Row label={t('parties.created')}><DateTime value={order.created_at} /></Row>
        <Row label={t('orders.completedAt')}><DateTime value={order.completed_at} /></Row>
      </dl>
    </div>
  )
}
