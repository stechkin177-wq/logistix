import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { Dialog } from '../../../shared/ui/Dialog'
import { Select } from '../../../shared/ui/Select'
import { Spinner } from '../../../shared/ui/Spinner'
import { TextArea } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import {
  applyProfile, disableModule, enableModule, getModules, getProfiles,
  type ActivityProfile, type CompanyModuleInfo, type ModulesResponse, type ProfileResult,
} from './api'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Blocks } from '../../../shared/ui/icons'

const KEY = ['company', 'modules'] as const

/** Название модуля: перевод по коду, при отсутствии - название из каталога сервера. */
function useModuleName(items: CompanyModuleInfo[]) {
  const { t } = useTranslation()
  return (code: string) => t(`modules.catalog.${code}.name`, { defaultValue: items.find((m) => m.code === code)?.name ?? code })
}

function DisableDialog({ module, items, onClose }: { module: CompanyModuleInfo; items: CompanyModuleInfo[]; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const nameOf = useModuleName(items)
  const [reason, setReason] = useState('')
  const [cascade, setCascade] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const busy = useRef(false)
  const dependents = module.dependents
  const hasDependents = dependents.length > 0
  const mutation = useMutation({
    mutationFn: () => disableModule(module.code, reason.trim(), cascade),
    onSuccess: (data) => {
      qc.setQueryData(KEY, data)
      void qc.invalidateQueries({ queryKey: ['session'] })
      pushToast('info', t('modules.disabledToast', { name: nameOf(module.code) }))
      onClose()
    },
    onError: (e) => { setError(errorMessage(e, t)) },
    onSettled: () => { busy.current = false },
  })
  const submit = () => {
    if (busy.current) return // повторная отправка, пока идёт запрос, игнорируется
    if (!reason.trim()) { setError(t('modules.reasonRequired')); return }
    if (hasDependents && !cascade) { setError(t('modules.cascadeRequired')); return }
    busy.current = true
    setError(undefined)
    mutation.mutate()
  }
  return (
    <Dialog
      open
      title={t('modules.disableTitle', { name: nameOf(module.code) })}
      busy={mutation.isPending}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={mutation.isPending}>{t('common.cancel')}</Button>
          <Button variant="danger" onClick={submit} disabled={mutation.isPending}>{t('modules.disable')}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm">{t('modules.disableNote')}</p>
        {hasDependents ? (
          <div className="space-y-1">
            <Banner kind="warning">{t('modules.blocker.module_has_dependents', { names: dependents.map(nameOf).join(', ') })}</Banner>
            <Checkbox
              label={t('modules.cascadeLabel', { names: dependents.map(nameOf).join(', ') })}
              checked={cascade}
              onChange={(e) => { setCascade(e.target.checked) }}
            />
          </div>
        ) : null}
        <TextArea label={t('modules.reason')} required value={reason} maxLength={500} onChange={(e) => { setReason(e.target.value) }} />
        {error ? <Banner kind="error">{error}</Banner> : null}
      </div>
    </Dialog>
  )
}

function ModuleRow({
  module, items, canWrite, busy, onEnable, onDisable,
}: {
  module: CompanyModuleInfo
  items: CompanyModuleInfo[]
  canWrite: boolean
  busy: boolean
  onEnable: (m: CompanyModuleInfo) => void
  onDisable: (m: CompanyModuleInfo) => void
}) {
  const { t } = useTranslation()
  const nameOf = useModuleName(items)
  const blocker = module.blocker
  // отключить можно открыть диалог и при наличии зависимых (там явное подтверждение каскада)
  const dependentsOnly = module.enabled && blocker?.code === 'module_has_dependents'
  const canToggle = !module.is_core && (module.enabled ? module.can_disable || dependentsOnly : module.can_enable)
  const hint = !module.is_core && blocker && !(module.enabled && module.can_disable)
    ? t(`modules.blocker.${blocker.code}`, { names: (blocker.modules ?? []).map(nameOf).join(', '), defaultValue: blocker.detail })
    : null
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-2">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{nameOf(module.code)}</span>
          {module.is_core ? <Badge tone="info">{t('modules.core')}</Badge> : null}
          {module.status === 'beta' ? <Badge tone="warning">{t('modules.beta')}</Badge> : null}
          {!module.available_in_plan ? <Badge tone="neutral">{t('modules.notInPlan')}</Badge> : null}
        </div>
        <p className="text-xs text-muted">{t(`modules.catalog.${module.code}.description`, { defaultValue: module.description })}</p>
        {module.requires.filter((c) => c !== 'core').length > 0 ? (
          <p className="text-xs text-muted">{t('modules.requires')}: {module.requires.filter((c) => c !== 'core').map(nameOf).join(', ')}</p>
        ) : null}
        {module.enhances.length > 0 ? (
          <p className="text-xs text-muted">{t('modules.enhances')}: {module.enhances.map(nameOf).join(', ')}</p>
        ) : null}
        {hint ? <p className="text-xs text-amber-700 dark:text-amber-300">{hint}</p> : null}
      </div>
      <Checkbox
        label={module.enabled ? t('modules.on') : t('modules.off')}
        aria-label={t('modules.toggle', { name: nameOf(module.code) })}
        checked={module.enabled}
        disabled={!canWrite || busy || module.is_core || !canToggle}
        onChange={() => { if (module.enabled) onDisable(module); else onEnable(module) }}
      />
    </li>
  )
}

function ProfileBlock({ items }: { items: CompanyModuleInfo[] }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const canWrite = useCanWrite('company.manage_modules')
  const nameOf = useModuleName(items)
  const profiles = useQuery({ queryKey: ['activity-profiles'], queryFn: ({ signal }) => getProfiles(signal) })
  const [code, setCode] = useState('')
  const [replace, setReplace] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [result, setResult] = useState<ProfileResult | null>(null)
  const busy = useRef(false)
  const profile: ActivityProfile | undefined = profiles.data?.find((p) => p.code === code)
  const apply = useMutation({
    mutationFn: () => applyProfile(code, replace, ''),
    onSuccess: (data: ModulesResponse) => {
      qc.setQueryData(KEY, data)
      void qc.invalidateQueries({ queryKey: ['session'] })
      void qc.invalidateQueries({ queryKey: ['activity-profiles'] })
      setResult(data.result ?? null)
      setConfirm(false)
      pushToast('info', t('modules.profileApplied'))
    },
    onError: (e) => { setError(errorMessage(e, t)) },
    onSettled: () => { busy.current = false },
  })
  const run = () => {
    if (busy.current) return
    busy.current = true
    setError(undefined)
    apply.mutate()
  }
  return (
    <section aria-labelledby="mod-profile" className="space-y-2 rounded-card border border-line bg-surface p-4 shadow-card">
      <h2 id="mod-profile" className="text-sm font-semibold">{t('modules.profileTitle')}</h2>
      <p className="text-xs text-muted">{t('modules.profileHint')}</p>
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={t('modules.profile')}
          value={code}
          placeholder={t('modules.profileNone')}
          options={(profiles.data ?? []).map((p) => ({ value: p.code, label: p.name }))}
          onChange={(v) => { setCode(v); setResult(null) }}
        />
        <Checkbox label={t('modules.replace')} checked={replace} onChange={(e) => { setReplace(e.target.checked) }} />
        <Button variant="primary" disabled={!canWrite || !profile} onClick={() => { setError(undefined); setConfirm(true) }}>{t('modules.apply')}</Button>
      </div>
      {profile ? (
        <p className="text-xs text-muted">
          {t('modules.profileModules')}: {profile.modules.map(nameOf).join(', ')}
          {profile.unavailable_modules.length > 0 ? ` - ${t('modules.profileUnavailable')}: ${profile.unavailable_modules.map(nameOf).join(', ')}` : ''}
        </p>
      ) : null}
      {result ? (
        <Banner kind={result.skipped.length > 0 ? 'warning' : 'info'}>
          <p>{t('modules.resultEnabled')}: {result.enabled.length > 0 ? result.enabled.map(nameOf).join(', ') : t('modules.none')}</p>
          {result.disabled.length > 0 ? <p>{t('modules.resultDisabled')}: {result.disabled.map(nameOf).join(', ')}</p> : null}
          {result.skipped.length > 0 ? <p>{t('modules.resultSkipped')}: {result.skipped.map((s) => nameOf(s.code)).join(', ')}</p> : null}
        </Banner>
      ) : null}
      <ConfirmDialog
        open={confirm && profile !== undefined}
        title={t('modules.applyTitle', { name: profile?.name ?? '' })}
        message={replace ? t('modules.applyReplaceMessage') : t('modules.applyMessage')}
        confirmLabel={t('modules.apply')}
        busy={apply.isPending}
        error={error}
        onConfirm={run}
        onCancel={() => { setConfirm(false) }}
      />
    </section>
  )
}

/** Настройки -> «Модули компании»: список с переключателями, зависимости, профили деятельности. */
export function ModulesPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const canWrite = useCanWrite('company.manage_modules')
  const query = useQuery({ queryKey: KEY, queryFn: ({ signal }) => getModules(signal) })
  const [disabling, setDisabling] = useState<CompanyModuleInfo | null>(null)
  const [error, setError] = useState<string | undefined>()
  const busy = useRef(false)
  const items = query.data?.modules ?? []
  const nameOf = useModuleName(items)
  const enable = useMutation({
    mutationFn: (code: string) => enableModule(code, ''),
    onSuccess: (data, code) => {
      qc.setQueryData(KEY, data)
      void qc.invalidateQueries({ queryKey: ['session'] })
      pushToast('info', t('modules.enabledToast', { name: nameOf(code) }))
    },
    onError: (e) => { setError(errorMessage(e, t)) },
    onSettled: () => { busy.current = false },
  })
  const onEnable = (m: CompanyModuleInfo) => {
    if (busy.current) return // защита от повторной отправки
    busy.current = true
    setError(undefined)
    enable.mutate(m.code)
  }
  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader icon={Blocks} title={t('nav.modules')} />
      <p className="text-sm text-muted">{t('modules.intro')}</p>
      {query.isError ? (
        <>
          <Banner kind="error">{errorMessage(query.error, t)}</Banner>
          <Button onClick={() => void query.refetch()}>{t('table.retry')}</Button>
        </>
      ) : !query.data ? <Spinner label={t('table.loading')} /> : (
        <>
          {error ? <Banner kind="error">{error}</Banner> : null}
          <ProfileBlock items={items} />
          <section aria-labelledby="mod-list" className="rounded-card border border-line bg-surface p-4 shadow-card">
            <h2 id="mod-list" className="text-sm font-semibold">{t('modules.listTitle')}</h2>
            <ul className="divide-y divide-line">
              {items.map((m) => (
                <ModuleRow
                  key={m.code}
                  module={m}
                  items={items}
                  canWrite={canWrite}
                  busy={enable.isPending}
                  onEnable={onEnable}
                  onDisable={(x) => { setError(undefined); setDisabling(x) }}
                />
              ))}
            </ul>
          </section>
        </>
      )}
      {disabling ? <DisableDialog module={disabling} items={items} onClose={() => { setDisabling(null) }} /> : null}
    </div>
  )
}
