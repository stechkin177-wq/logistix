import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { EmptyState } from '../../shared/ui/EmptyState'
import { PlanDrawer } from './PlanDrawer'
import { useDeletePlan, usePlanAction, usePlans, useReorder } from './hooks'
import type { AdminPlan, PlanStatus } from './types'

const TONE: Record<PlanStatus, 'neutral' | 'success' | 'warning'> = { draft: 'neutral', active: 'success', archived: 'warning' }

/** Администратор платформы: тарифы - создание, состав, лимиты, статусы, порядок, тариф по умолчанию. */
export function PlansPage() {
  const { t } = useTranslation()
  const plans = usePlans()
  const action = usePlanAction()
  const remove = useDeletePlan()
  const reorder = useReorder()
  const [editor, setEditor] = useState<{ plan: AdminPlan | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<AdminPlan | null>(null)
  const [error, setError] = useState<string>()
  const rows = plans.data ?? []

  const run = (code: string, name: 'publish' | 'unpublish' | 'archive' | 'restore' | 'set-default') => {
    setError(undefined)
    action.mutate({ code, action: name }, { onError: (e) => { setError(errorMessage(e, t)) } })
  }
  const move = (index: number, delta: number) => {
    const codes = rows.map((p) => p.code)
    const target = index + delta
    if (target < 0 || target >= codes.length) return
    const [item] = codes.splice(index, 1)
    if (item === undefined) return
    codes.splice(target, 0, item)
    setError(undefined)
    reorder.mutate(codes, { onError: (e) => { setError(errorMessage(e, t)) } })
  }

  const columns: Column<AdminPlan>[] = [
    {
      key: 'order',
      header: t('platform.plans.order'),
      cell: (p) => {
        const index = rows.findIndex((x) => x.code === p.code)
        return (
          <span className="flex gap-1">
            <Button variant="ghost" aria-label={t('platform.plans.moveUp', { name: p.name })} disabled={index === 0 || reorder.isPending} onClick={() => { move(index, -1) }}>↑</Button>
            <Button variant="ghost" aria-label={t('platform.plans.moveDown', { name: p.name })} disabled={index === rows.length - 1 || reorder.isPending} onClick={() => { move(index, 1) }}>↓</Button>
          </span>
        )
      },
    },
    {
      key: 'name',
      header: t('platform.plans.name'),
      cell: (p) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ plan: p, nonce: Date.now() }) }}>
          {p.name} <span className="text-xs text-slate-500">({p.code})</span>
        </button>
      ),
    },
    { key: 'price', header: t('platform.plans.price'), align: 'right', cell: (p) => `${p.price} ${p.currency} / ${t(`platform.plans.periods.${p.billing_type}`)}` },
    {
      key: 'status',
      header: t('common.status'),
      cell: (p) => (
        <span className="flex flex-wrap gap-1">
          <Badge tone={TONE[p.status]}>{t(`platform.plans.status.${p.status}`)}</Badge>
          {p.is_default ? <Badge tone="info">{t('platform.plans.default')}</Badge> : null}
        </span>
      ),
    },
    { key: 'subs', header: t('platform.plans.subscriptions'), align: 'right', cell: (p) => p.subscriptions_count },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (p) => (
        <span className="flex flex-wrap justify-end gap-1">
          {p.status === 'draft' ? <Button variant="ghost" onClick={() => { run(p.code, 'publish') }}>{t('platform.plans.publish')}</Button> : null}
          {p.status === 'active' && !p.is_default ? <Button variant="ghost" onClick={() => { run(p.code, 'unpublish') }}>{t('platform.plans.unpublish')}</Button> : null}
          {p.status === 'active' && !p.is_default ? <Button variant="ghost" onClick={() => { run(p.code, 'set-default') }}>{t('platform.plans.makeDefault')}</Button> : null}
          {p.status !== 'archived' && !p.is_default ? <Button variant="ghost" onClick={() => { run(p.code, 'archive') }}>{t('platform.plans.archive')}</Button> : null}
          {p.status === 'archived' ? <Button variant="ghost" onClick={() => { run(p.code, 'restore') }}>{t('platform.plans.restore')}</Button> : null}
          {!p.is_default ? <Button variant="ghost" aria-label={t('platform.plans.deleteNamed', { name: p.name })} onClick={() => { setToDelete(p) }}>{t('common.delete')}</Button> : null}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.platformPlans')}</h1>
        <Button variant="primary" onClick={() => { setEditor({ plan: null, nonce: Date.now() }) }}>{t('platform.plans.new')}</Button>
      </div>
      <p className="text-sm text-slate-500">{t('platform.plans.intro')}</p>
      {error ? <Banner kind="error">{error}</Banner> : null}
      <DataTable
        caption={t('nav.platformPlans')}
        columns={columns}
        rows={plans.data}
        rowKey={(p) => p.code}
        loading={plans.isFetching}
        error={plans.isError ? errorMessage(plans.error, t) : undefined}
        onRetry={() => void plans.refetch()}
        empty={<EmptyState title={t('platform.plans.empty')} hint={t('platform.plans.emptyHint')} />}
      />
      {editor ? <PlanDrawer key={editor.nonce} plan={editor.plan} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('platform.plans.deleteTitle')}
        message={t('platform.plans.deleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.code, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
