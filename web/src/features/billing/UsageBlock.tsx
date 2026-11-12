import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Spinner } from '../../shared/ui/Spinner'
import { useUsage, type LimitState } from './usage'

const TONE: Record<LimitState, 'success' | 'info' | 'warning' | 'danger'> = {
  ok: 'success', near: 'warning', reached: 'warning', exceeded: 'danger',
}

/** Лимиты тарифа и фактическое использование; предупреждения «приближается / достигнут / превышен». */
export function UsageBlock() {
  const { t } = useTranslation()
  const usage = useUsage()
  const rows = (usage.data?.results ?? []).filter((r) => r.enforced && r.limit !== null)
  return (
    <section aria-labelledby="usage-title" className="space-y-2 rounded-card border border-line bg-surface p-4 shadow-card">
      <h2 id="usage-title" className="text-sm font-semibold">{t('billing.usage.title')}</h2>
      {usage.isError ? <Banner kind="error">{errorMessage(usage.error, t)}</Banner> : null}
      {!usage.data && !usage.isError ? <Spinner label={t('table.loading')} /> : null}
      {usage.data && rows.length === 0 ? <p className="text-sm text-muted">{t('billing.usage.noLimits')}</p> : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-slate-200 text-sm">
          {rows.map((r) => (
            <li key={r.code} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span>
                {r.name}
                {r.scope === 'month' ? ` (${t('billing.usage.perMonth')})` : ''}
              </span>
              <span className="flex items-center gap-2">
                <b>{r.usage ?? '—'}</b> {t('billing.usage.of')} {r.limit}
                {r.state !== 'ok' ? <Badge tone={TONE[r.state]}>{t(`billing.usage.state.${r.state}`)}</Badge> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {rows.some((r) => r.state === 'exceeded') ? <p className="text-xs text-muted">{t('billing.usage.exceededHint')}</p> : null}
    </section>
  )
}
