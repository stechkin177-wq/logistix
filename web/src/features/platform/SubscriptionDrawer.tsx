import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateTime } from '../../shared/ui/DateTime'
import { Drawer } from '../../shared/ui/Drawer'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { useChangePlan, usePlans, usePreview, useRenew, useSubscription } from './hooks'
import type { PlatformCompany } from './types'

/** Подписка компании: период и цена, история периодов, смена тарифа с анализом последствий, продление. */
export function SubscriptionDrawer({ company, onClose }: { company: PlatformCompany; onClose: () => void }) {
  const { t } = useTranslation()
  const sub = useSubscription(company.id)
  const plans = usePlans()
  const [target, setTarget] = useState('')
  const [period, setPeriod] = useState<'keep' | 'restart'>('keep')
  const [periods, setPeriods] = useState('1')
  const [error, setError] = useState<string>()
  const preview = usePreview(company.id, target)
  const change = useChangePlan(company.id)
  const renew = useRenew(company.id)
  const p = preview.data
  const options = (plans.data ?? []).filter((x) => x.status !== 'archived' && x.code !== sub.data?.plan)

  return (
    <Drawer open title={company.name} onClose={onClose} busy={change.isPending || renew.isPending} width="max-w-2xl">
      {error ? <Banner kind="error">{error}</Banner> : null}
      {!sub.data && !sub.isError ? <Spinner label={t('table.loading')} /> : null}
      {sub.isError ? <Banner kind="error">{errorMessage(sub.error, t)}</Banner> : null}
      {sub.data ? (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <div><dt className="text-xs text-slate-500">{t('platform.companies.plan')}</dt><dd>{sub.data.plan}</dd></div>
            <div><dt className="text-xs text-slate-500">{t('common.status')}</dt><dd><Badge tone={sub.data.status === 'active' || sub.data.status === 'trial' ? 'success' : 'warning'}>{t(`company.statuses.${sub.data.status}`)}</Badge></dd></div>
            <div><dt className="text-xs text-slate-500">{t('company.endsAt')}</dt><dd>{sub.data.ends_at ? <DateTime value={sub.data.ends_at} dateOnly /> : t('company.unlimited')}</dd></div>
            <div>
              <dt className="text-xs text-slate-500">{t('platform.companies.currentPrice')}</dt>
              <dd>{sub.data.current_period ? `${sub.data.current_period.price} ${sub.data.current_period.currency}${sub.data.current_period.is_free ? ` (${t('company.freePeriod')})` : ''}` : '—'}</dd>
            </div>
          </dl>

          <section aria-label={t('platform.companies.changePlan')} className="space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700">
            <h3 className="text-sm font-semibold">{t('platform.companies.changePlan')}</h3>
            <div className="grid grid-cols-2 gap-2">
              <Select label={t('platform.companies.newPlan')} value={target} placeholder="—" options={options.map((x) => ({ value: x.code, label: `${x.name} (${x.code})` }))} onChange={setTarget} />
              <Select
                label={t('platform.companies.periodMode')}
                value={period}
                options={[{ value: 'keep', label: t('platform.companies.keep') }, { value: 'restart', label: t('platform.companies.restart') }]}
                onChange={(v) => { setPeriod(v === 'restart' ? 'restart' : 'keep') }}
              />
            </div>
            {target && preview.isFetching ? <Spinner label={t('table.loading')} /> : null}
            {p ? (
              <div className="space-y-1 text-sm" aria-label={t('platform.companies.impact')} role="group">
                <div className="font-medium">{t('platform.companies.impact')}</div>
                <div>{t('platform.companies.price')}: {p.price.current_period ?? '—'} → {p.price.new} {p.price.currency}</div>
                {p.lost_modules.length > 0 ? <div>{t('platform.companies.lostModules')}: {p.lost_modules.join(', ')}</div> : null}
                {p.gained_modules.length > 0 ? <div>{t('platform.companies.gainedModules')}: {p.gained_modules.join(', ')}</div> : null}
                {p.lost_features.length > 0 ? <div>{t('platform.companies.lostFeatures')}: {p.lost_features.join(', ')}</div> : null}
                {p.gained_features.length > 0 ? <div>{t('platform.companies.gainedFeatures')}: {p.gained_features.join(', ')}</div> : null}
                {p.limits_exceeded.map((l) => (
                  <div key={l.code} className="text-red-700 dark:text-red-300">
                    {t('platform.companies.limitExceeded', { name: l.name, usage: l.usage ?? 0, limit: l.new_limit ?? 0 })}
                  </div>
                ))}
                {p.limits_tightened.map((l) => (
                  <div key={l.code}>{t('platform.companies.limitTightened', { name: l.name, usage: l.usage ?? 0, limit: l.new_limit ?? 0 })}</div>
                ))}
                <p className="text-xs text-slate-500">{t('platform.companies.safeHint')}</p>
              </div>
            ) : null}
            <Button
              variant="primary"
              disabled={!target || change.isPending}
              onClick={() => {
                setError(undefined)
                change.mutate({ plan: target, period }, { onSuccess: () => { setTarget('') }, onError: (e) => { setError(errorMessage(e, t)) } })
              }}
            >
              {t('platform.companies.apply')}
            </Button>
          </section>

          <section aria-label={t('platform.companies.renew')} className="space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700">
            <h3 className="text-sm font-semibold">{t('platform.companies.renew')}</h3>
            <div className="flex items-end gap-2">
              <TextField label={t('platform.companies.periodsCount')} inputMode="numeric" value={periods} onChange={(e) => { setPeriods(e.target.value.replace(/\D/g, '')) }} />
              <Button
                disabled={renew.isPending || !periods}
                onClick={() => {
                  setError(undefined)
                  renew.mutate(Number(periods), { onError: (e) => { setError(errorMessage(e, t)) } })
                }}
              >
                {t('platform.companies.renewAction')}
              </Button>
            </div>
            <p className="text-xs text-slate-500">{t('platform.companies.renewHint')}</p>
          </section>

          <section aria-label={t('platform.companies.periods')}>
            <h3 className="text-sm font-semibold">{t('platform.companies.periods')}</h3>
            <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
              {[...sub.data.periods].reverse().map((x, i) => (
                <li key={`${x.starts_at}-${String(i)}`} className="py-1">
                  {x.starts_at.slice(0, 10)} — {x.ends_at ? x.ends_at.slice(0, 10) : t('company.unlimited')} · {x.plan} · <b>{x.price} {x.currency}</b> · {t(`platform.companies.reason.${x.reason}`)}
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}
    </Drawer>
  )
}
