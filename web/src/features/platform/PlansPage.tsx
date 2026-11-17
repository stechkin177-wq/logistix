import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { PlanDrawer } from './PlanDrawer'
import { useDeletePlan, usePlanAction, usePlans, useReorder } from './hooks'
import type { AdminPlan, PlanStatus } from './types'
import { ManageHeader } from './ManageHeader'
import { Plus, Archive, ArchiveRestore, ArrowDown, ArrowUp, EyeOff, Rocket, Star, Trash2 } from '../../shared/ui/icons'

const TONE: Record<PlanStatus, 'neutral' | 'success' | 'warning'> = { draft: 'neutral', active: 'success', archived: 'warning' }

/** Администратор платформы: тарифы - создание, состав, лимиты, статусы, порядок, тариф по умолчанию. */
export function PlansPage() {
  const { t } = useTranslation()
  const { money } = useFormat()
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

  return (
    <div className="space-y-3">
      <ManageHeader
        active="plans"
        actions={<Button variant="primary" icon={Plus} onClick={() => { setEditor({ plan: null, nonce: Date.now() }) }}>{t('platform.plans.new')}</Button>}
      />
      {error ? <Banner kind="error">{error}</Banner> : null}
      {plans.isError ? (
        <Banner kind="error">{errorMessage(plans.error, t)} <Button onClick={() => void plans.refetch()}>{t('common.retry')}</Button></Banner>
      ) : rows.length === 0 && !plans.isFetching ? (
        <EmptyState title={t('platform.plans.empty')} hint={t('platform.plans.emptyHint')} />
      ) : (
        <ul aria-label={t('nav.platformPlans')} className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {rows.map((p, index) => (
            <li key={p.code} className="flex flex-col gap-2.5 rounded-card border border-line bg-surface p-3 shadow-card md:p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <button type="button" className="block max-w-full truncate text-left text-base font-semibold text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ plan: p, nonce: Date.now() }) }}>
                    {p.name} <span className="text-xs font-normal text-muted">({p.code})</span>
                  </button>
                  <p className="mt-0.5 text-sm text-ink">{money(p.price, p.currency)} / {t(`platform.plans.periods.${p.billing_type}`)}</p>
                </div>
                <span className="flex shrink-0 flex-wrap justify-end gap-1">
                  <Badge tone={TONE[p.status]}>{t(`platform.plans.status.${p.status}`)}</Badge>
                  {p.is_default ? <Badge tone="info">{t('platform.plans.default')}</Badge> : null}
                </span>
              </div>
              <p className="text-xs text-muted">{t('platform.plans.subscriptions')}: <b className="text-ink">{p.subscriptions_count}</b></p>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5">
                <span className="flex gap-1">
                  <Button variant="secondary" className="size-8! p-0!" aria-label={t('platform.plans.moveUp', { name: p.name })} disabled={index === 0 || reorder.isPending} onClick={() => { move(index, -1) }}><ArrowUp className="size-4" aria-hidden="true" /></Button>
                  <Button variant="secondary" className="size-8! p-0!" aria-label={t('platform.plans.moveDown', { name: p.name })} disabled={index === rows.length - 1 || reorder.isPending} onClick={() => { move(index, 1) }}><ArrowDown className="size-4" aria-hidden="true" /></Button>
                </span>
                {p.status === 'draft' ? <Button variant="secondary" className="h-8! gap-1.5! px-2.5! text-xs!" icon={Rocket} onClick={() => { run(p.code, 'publish') }}>{t('platform.plans.publish')}</Button> : null}
                {p.status === 'active' && !p.is_default ? <Button variant="secondary" className="h-8! gap-1.5! px-2.5! text-xs!" icon={EyeOff} onClick={() => { run(p.code, 'unpublish') }}>{t('platform.plans.unpublish')}</Button> : null}
                {p.status === 'active' && !p.is_default ? <Button variant="secondary" className="h-8! gap-1.5! px-2.5! text-xs!" icon={Star} onClick={() => { run(p.code, 'set-default') }}>{t('platform.plans.makeDefault')}</Button> : null}
                {p.status !== 'archived' && !p.is_default ? <Button variant="secondary" className="h-8! gap-1.5! px-2.5! text-xs!" icon={Archive} onClick={() => { run(p.code, 'archive') }}>{t('platform.plans.archive')}</Button> : null}
                {p.status === 'archived' ? <Button variant="secondary" className="h-8! gap-1.5! px-2.5! text-xs!" icon={ArchiveRestore} onClick={() => { run(p.code, 'restore') }}>{t('platform.plans.restore')}</Button> : null}
                {!p.is_default ? <Button variant="dangerSoft" className="ml-auto h-8! gap-1.5! px-2.5! text-xs!" icon={Trash2} aria-label={t('platform.plans.deleteNamed', { name: p.name })} onClick={() => { setToDelete(p) }}>{t('common.delete')}</Button> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
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
