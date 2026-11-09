import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { DateInput } from '../../../shared/ui/DateInput'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Select } from '../../../shared/ui/Select'
import { Spinner } from '../../../shared/ui/Spinner'
import { TextField } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { BrandingBlock } from './BrandingBlock'
import { UsageBlock } from '../../billing/UsageBlock'
import { SubscriptionBlock } from './SubscriptionBlock'
import { timeZones } from './timezones'

interface CompanySettings {
  name: string
  timezone: string
  language: 'ru' | 'kk'
  accounting_start: string | null
}

function CompanyForm({ settings }: { settings: CompanySettings }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const canSave = useCanWrite('company.update')
  const zones = useMemo(() => timeZones(), [])
  const [form, setForm] = useState({
    name: settings.name,
    timezone: settings.timezone,
    language: settings.language,
    accounting_start: settings.accounting_start ?? '',
  })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const save = useMutation({
    mutationFn: (body: CompanySettings) => api.patch<CompanySettings>('/company/settings/', body),
    onSuccess: async () => {
      // пояс и язык компании приходят из сессии
      await Promise.all([qc.invalidateQueries({ queryKey: ['session'] }), qc.invalidateQueries({ queryKey: ['company'] })])
      pushToast('info', t('company.saved'))
    },
    onError: (error) => { setErrors(serverErrors(error, t, (p) => ['name', 'timezone', 'language', 'accounting_start'].includes(p))) },
  })
  const submit = () => {
    if (!form.name.trim()) {
      setErrors({ fields: { name: t('errors.requiredField') }, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate({ name: form.name.trim(), timezone: form.timezone.trim(), language: form.language, accounting_start: form.accounting_start || null })
  }
  const f = errors.fields
  return (
    <form ref={ref} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSave) submit() }}>
      <FormBanner message={errors.banner} />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <TextField label={t('company.name')} required value={form.name} disabled={!canSave} error={f.name} onChange={(e) => { setForm((s) => ({ ...s, name: e.target.value })) }} />
        <div>
          <TextField label={t('company.timezone')} list="tz-list" value={form.timezone} disabled={!canSave} error={f.timezone} hint={t('company.timezoneHint')} onChange={(e) => { setForm((s) => ({ ...s, timezone: e.target.value })) }} />
          <datalist id="tz-list">{zones.map((z) => <option key={z} value={z} />)}</datalist>
        </div>
        <Select label={t('company.language')} value={form.language} disabled={!canSave} error={f.language} options={[{ value: 'ru', label: t('languages.ru') }, { value: 'kk', label: t('languages.kk') }]} onChange={(v) => { setForm((s) => ({ ...s, language: v === 'kk' ? 'kk' : 'ru' })) }} />
        <DateInput label={t('company.accountingStart')} value={form.accounting_start} disabled={!canSave} error={f.accounting_start} onChange={(v) => { setForm((s) => ({ ...s, accounting_start: v })) }} />
      </div>
      <div className="flex justify-end">
        <WriteButton permission="company.update" variant="primary" type="submit" disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</WriteButton>
      </div>
    </form>
  )
}

/** Компания: общие настройки, оформление и лицензия. */
export function CompanyPage() {
  const { t } = useTranslation()
  const query = useQuery({ queryKey: ['company', 'settings'], queryFn: ({ signal }) => api.get<CompanySettings>('/company/settings/', undefined, { signal }) })
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-base font-semibold">{t('nav.company')}</h1>
      <section aria-labelledby="company-main" className="space-y-2 rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <h2 id="company-main" className="text-sm font-semibold">{t('company.main')}</h2>
        {query.isError ? (
          <>
            <Banner kind="error">{errorMessage(query.error, t)}</Banner>
            <Button onClick={() => void query.refetch()}>{t('table.retry')}</Button>
          </>
        ) : query.data ? <CompanyForm settings={query.data} /> : <Spinner label={t('table.loading')} />}
      </section>
      <BrandingBlock />
      <SubscriptionBlock />
      <UsageBlock />
    </div>
  )
}
