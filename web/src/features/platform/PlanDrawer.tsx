import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { Drawer } from '../../shared/ui/Drawer'
import { FormBanner } from '../../shared/ui/FormBanner'
import { Select } from '../../shared/ui/Select'
import { Tabs } from '../../shared/ui/Tabs'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { useCatalog, useSavePlan } from './hooks'
import type { AdminPlan, BillingType, Catalog } from './types'

type TabKey = 'main' | 'content' | 'limits'
const TABS: TabKey[] = ['main', 'content', 'limits']
const PERIODS: BillingType[] = ['monthly', 'yearly', 'lifetime']
const CODE_RE = /^[a-z0-9][a-z0-9_-]{0,49}$/

/** Модули с учётом жёстких зависимостей: добавление тянет зависимости, снятие снимает зависящие. */
function toggleModule(catalog: Catalog, modules: string[], code: string, on: boolean): string[] {
  const set = new Set(modules)
  const add = (c: string) => {
    if (set.has(c)) return
    set.add(c)
    catalog.modules.find((m) => m.code === c)?.requires.forEach(add)
  }
  const remove = (c: string) => {
    set.delete(c)
    catalog.modules.filter((m) => m.requires.includes(c)).forEach((m) => { if (set.has(m.code)) remove(m.code) })
  }
  if (on) add(code)
  else remove(code)
  return [...set]
}

/** Карточка тарифа: основное, состав (модули и функции), лимиты. Создание и правка. */
export function PlanDrawer({ plan, onClose }: { plan: AdminPlan | null; onClose: () => void }) {
  const { t } = useTranslation()
  const catalog = useCatalog().data
  const save = useSavePlan()
  const creating = plan === null
  const [tab, setTab] = useState<TabKey>('main')
  const [error, setError] = useState<string>()
  const [form, setForm] = useState(() => ({
    code: plan?.code ?? '',
    name: plan?.name ?? '',
    description: plan?.description ?? '',
    billing_type: plan?.billing_type ?? ('monthly'),
    price: plan?.price ?? '0',
    currency: plan?.currency ?? 'KZT',
    free_period_days: String(plan?.free_period_days ?? 0),
    limit_warn_percent: String(plan?.limit_warn_percent ?? 80),
  }))
  const [modules, setModules] = useState<string[]>(plan?.modules ?? [])
  const [features, setFeatures] = useState<Record<string, boolean | string>>(plan?.features ?? {})
  const [limits, setLimits] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(plan?.limits ?? {}).map(([k, v]) => [k, v === null ? '' : String(v)])),
  )
  const set = (key: keyof typeof form, value: string) => { setForm((f) => ({ ...f, [key]: value })) }

  const submit = () => {
    setError(undefined)
    if (creating && !CODE_RE.test(form.code)) { setError(t('platform.plans.codeHint')); return }
    if (!form.name.trim()) { setError(`${t('platform.plans.name')}: ${t('errors.requiredField')}`); return }
    const body: Record<string, unknown> = {
      name: form.name,
      description: form.description,
      billing_type: form.billing_type,
      price: form.price,
      currency: form.currency,
      free_period_days: Number(form.free_period_days),
      limit_warn_percent: Number(form.limit_warn_percent),
      modules,
      features: Object.fromEntries(Object.entries(features).filter(([, v]) => v !== false && v !== '')),
      limits: Object.fromEntries((catalog?.limits ?? []).map((l) => [l.code, limits[l.code] ? Number(limits[l.code]) : null])),
    }
    save.mutate(
      { code: plan?.code ?? form.code, body, create: creating },
      { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }

  return (
    <Drawer
      open
      title={creating ? t('platform.plans.new') : `${plan.name} (${plan.code})`}
      onClose={onClose}
      busy={save.isPending}
      width="max-w-2xl"
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</Button>
        </>
      }
    >
      <Tabs label={t('platform.plans.tabsLabel')} tabs={TABS.map((k) => ({ key: k, label: t(`platform.plans.tabs.${k}`) }))} active={tab} onChange={(k) => { setTab(k as TabKey) }} />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-3 space-y-3">
        <FormBanner message={error} />
        {tab === 'main' ? (
          <div className="grid grid-cols-2 gap-3">
            {creating ? <TextField label={t('platform.plans.code')} hint={t('platform.plans.codeHint')} required value={form.code} onChange={(e) => { set('code', e.target.value.toLowerCase()) }} /> : null}
            <TextField label={t('platform.plans.name')} required value={form.name} onChange={(e) => { set('name', e.target.value) }} />
            <TextArea fieldClassName="col-span-2" label={t('platform.plans.description')} value={form.description} onChange={(e) => { set('description', e.target.value) }} />
            <TextField label={t('platform.plans.price')} inputMode="decimal" value={form.price} onChange={(e) => { set('price', e.target.value) }} />
            <TextField label={t('platform.plans.currency')} hint={t('platform.plans.currencyHint')} value={form.currency} onChange={(e) => { set('currency', e.target.value.toUpperCase()) }} />
            <Select label={t('platform.plans.period')} value={form.billing_type} options={PERIODS.map((p) => ({ value: p, label: t(`platform.plans.periods.${p}`) }))} onChange={(v) => { set('billing_type', v) }} />
            <TextField label={t('platform.plans.freePeriod')} hint={t('platform.plans.freePeriodHint')} inputMode="numeric" value={form.free_period_days} onChange={(e) => { set('free_period_days', e.target.value) }} />
            <TextField label={t('platform.plans.warnPercent')} hint={t('platform.plans.warnPercentHint')} inputMode="numeric" value={form.limit_warn_percent} onChange={(e) => { set('limit_warn_percent', e.target.value) }} />
          </div>
        ) : null}
        {tab === 'content' && catalog ? (
          <>
            <h3 className="text-sm font-semibold">{t('platform.plans.modules')}</h3>
            <ul className="space-y-1">
              {catalog.modules.map((m) => (
                <li key={m.code}>
                  <Checkbox
                    label={`${m.name}${m.requires.length ? ` — ${t('platform.plans.requires')}: ${m.requires.join(', ')}` : ''}`}
                    checked={modules.includes(m.code)}
                    onChange={(e) => {
                      const next = toggleModule(catalog, modules, m.code, e.target.checked)
                      setModules(next)
                      setFeatures((f) => Object.fromEntries(Object.entries(f).filter(([k]) => {
                        const spec = catalog.features.find((x) => x.code === k)
                        return !spec || spec.module === 'core' || next.includes(spec.module)
                      })))
                    }}
                  />
                </li>
              ))}
            </ul>
            <h3 className="text-sm font-semibold">{t('platform.plans.features')}</h3>
            <ul className="space-y-2">
              {catalog.features.map((f) => {
                const available = f.module === 'core' || modules.includes(f.module)
                return (
                  <li key={f.code} className="flex items-center justify-between gap-2">
                    <span className={available ? '' : 'text-slate-400'}>
                      {f.name}
                      {!available ? ` (${t('platform.plans.needsModule', { module: f.module })})` : ''}
                    </span>
                    {f.kind === 'bool' ? (
                      <Checkbox label={f.name} hideLabel disabled={!available} checked={features[f.code] === true} onChange={(e) => { setFeatures((s) => ({ ...s, [f.code]: e.target.checked })) }} />
                    ) : (
                      <Select
                        label={f.name}
                        hideLabel
                        disabled={!available}
                        value={typeof features[f.code] === 'string' ? String(features[f.code]) : ''}
                        placeholder={t('platform.plans.featureOff')}
                        options={(f.levels ?? []).map((l) => ({ value: l, label: l }))}
                        onChange={(v) => { setFeatures((s) => ({ ...s, [f.code]: v })) }}
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          </>
        ) : null}
        {tab === 'limits' && catalog ? (
          <>
            <p className="text-sm text-slate-500">{t('platform.plans.limitsHint')}</p>
            <ul className="space-y-2">
              {catalog.limits.map((l) => (
                <li key={l.code} className="flex items-center justify-between gap-2">
                  <span>
                    {l.name}
                    {l.scope === 'month' ? ` (${t('billing.usage.perMonth')})` : ''}
                    {!l.enforced ? ` — ${t('platform.plans.notEnforced')}` : ''}
                  </span>
                  <TextField
                    label={l.name}
                    hideLabel
                    inputMode="numeric"
                    placeholder={t('platform.plans.unlimited')}
                    value={limits[l.code] ?? ''}
                    onChange={(e) => { setLimits((s) => ({ ...s, [l.code]: e.target.value.replace(/\D/g, '') })) }}
                  />
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Drawer>
  )
}
