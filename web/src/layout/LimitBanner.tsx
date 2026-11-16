import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { onApiEvent } from '../shared/api/events'
import { useUsage } from '../features/billing/usage'
import { useSession } from '../shared/auth/useSession'
import { Button } from '../shared/ui/Button'
import { Dialog } from '../shared/ui/Dialog'

/**
 * Окно «Лимит тарифа»: появляется только при попытке превысить лимит (ответ сервера limit_exceeded),
 * а не висит на экране. Показывает, какие ограничения исчерпаны.
 */
export function LimitDialog() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const usage = useUsage(open && hasPermission('company.manage_modules'))
  useEffect(() => onApiEvent('limit', () => {
    setOpen(true)
    void qc.invalidateQueries({ queryKey: ['billing', 'usage'] })
  }), [qc])
  if (!open) return null
  const rows = (usage.data?.warnings ?? []).filter((w) => w.state === 'reached' || w.state === 'exceeded')
  const close = () => { setOpen(false) }
  return (
    <Dialog
      open
      title={t('billing.usage.dialogTitle')}
      onClose={close}
      footer={
        <>
          <Button onClick={close}>{t('common.close')}</Button>
          {hasPermission('company.manage_modules') ? (
            <Link to="/settings/company" onClick={close} className="inline-flex h-9 items-center rounded-control bg-brand-600 px-3.5 text-sm font-medium text-brand-fg hover:bg-brand-solid-hover">{t('billing.usage.details')}</Link>
          ) : null}
        </>
      }
    >
      <div className="space-y-2 text-sm">
        <p>{t('billing.usage.dialogText')}</p>
        {rows.length > 0 ? (
          <ul className="space-y-1">
            {rows.map((r) => (
              <li key={r.code} className="flex items-center justify-between gap-3 rounded-control border border-line bg-surface-2 px-3 py-1.5">
                <span>{r.name}</span>
                <span className="tabular-nums text-muted">{r.usage ?? 0} / {r.limit ?? '∞'}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Dialog>
  )
}
