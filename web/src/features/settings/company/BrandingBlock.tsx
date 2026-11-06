import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { applyBranding, safeLogoUrl } from '../../../shared/branding/applyBranding'
import { isHexColor } from '../../../shared/branding/palette'
import type { Branding, Theme } from '../../../shared/api/types'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { FIELD_CLASS } from '../../../shared/ui/fieldStyles'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { FormField } from '../../../shared/ui/FormField'
import { Select } from '../../../shared/ui/Select'
import { Spinner } from '../../../shared/ui/Spinner'
import { TextField } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'

export const LOGO_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp']
export const LOGO_MAX_BYTES = 1024 * 1024

/** Предпроверка логотипа (как на сервере): расширение и размер. Возвращает ключ i18n ошибки или null. */
export function logoProblem(file: File): 'badType' | 'tooBig' | 'empty' | null {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!LOGO_EXTENSIONS.includes(ext)) return 'badType'
  if (file.size > LOGO_MAX_BYTES) return 'tooBig'
  if (file.size === 0) return 'empty'
  return null
}

interface FormState { app_name: string; color: string; theme: Theme }

function BrandingForm({ branding }: { branding: Branding }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { session } = useSession()
  const canSave = useCanWrite('company.update')
  const [form, setForm] = useState<FormState>({ app_name: branding.app_name, color: branding.primary_color, theme: branding.theme })
  const [logo, setLogo] = useState<File | null>(null)
  const [clearLogo, setClearLogo] = useState(false)
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const fileRef = useRef<HTMLInputElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusInvalid(formRef, errors)
  const sessionBranding = useRef(session?.branding)
  useEffect(() => {
    sessionBranding.current = session?.branding
  }, [session?.branding])
  const colorOk = isHexColor(form.color)

  // предпросмотр: только применение к документу; при уходе со страницы возвращается сохранённое оформление
  useEffect(() => {
    if (!colorOk) return
    applyBranding({ app_name: form.app_name, logo_url: null, primary_color: form.color, theme: form.theme })
    return () => {
      if (sessionBranding.current) applyBranding(sessionBranding.current)
    }
  }, [form.app_name, form.color, form.theme, colorOk])

  const save = useMutation({
    mutationFn: (body: FormData) => api.upload<Branding>('/company/branding/', body, 'PATCH'),
    onSuccess: async () => {
      setLogo(null)
      setClearLogo(false)
      if (fileRef.current) fileRef.current.value = ''
      await Promise.all([qc.invalidateQueries({ queryKey: ['session'] }), qc.invalidateQueries({ queryKey: ['company', 'branding'] })])
      pushToast('info', t('company.brandingSaved'))
    },
    onError: (error) => { setErrors(serverErrors(error, t, (p) => ['app_name', 'primary_color', 'theme', 'logo'].includes(p))) },
  })

  const submit = () => {
    const local: Record<string, string> = {}
    if (!colorOk) local.primary_color = t('company.colorInvalid')
    if (form.app_name.length > 64) local.app_name = t('company.appNameLong')
    if (logo) {
      const problem = logoProblem(logo)
      if (problem) local.logo = t(`company.logo.${problem}`)
    }
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    const body = new FormData()
    body.set('app_name', form.app_name.trim())
    body.set('primary_color', form.color.toUpperCase())
    body.set('theme', form.theme)
    if (logo) body.set('logo', logo)
    else if (clearLogo) body.set('logo', '')
    save.mutate(body)
  }

  const f = errors.fields
  const logoUrl = clearLogo ? null : safeLogoUrl(branding.logo_url)
  return (
    <form ref={formRef} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSave) submit() }}>
      <FormBanner message={errors.banner} />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <TextField label={t('company.appName')} value={form.app_name} maxLength={64} disabled={!canSave} error={f.app_name} onChange={(e) => { setForm((s) => ({ ...s, app_name: e.target.value })) }} />
        <Select
          label={t('company.theme')}
          value={form.theme}
          disabled={!canSave}
          options={(['light', 'dark', 'system'] as const).map((v) => ({ value: v, label: t(`company.themes.${v}`) }))}
          onChange={(v) => { setForm((s) => ({ ...s, theme: v === 'dark' || v === 'system' ? v : 'light' })) }}
        />
        <div className="flex items-end gap-2">
          <input
            type="color"
            aria-label={t('company.colorPicker')}
            value={colorOk ? form.color.toLowerCase() : '#000000'}
            disabled={!canSave}
            className="h-8 w-10 cursor-pointer rounded border border-slate-300 p-0.5"
            onChange={(e) => { setForm((s) => ({ ...s, color: e.target.value.toUpperCase() })) }}
          />
          <TextField fieldClassName="flex-1" label={t('company.primaryColor')} value={form.color} maxLength={7} disabled={!canSave} error={f.primary_color} hint={t('company.colorHint')} onChange={(e) => { setForm((s) => ({ ...s, color: e.target.value })) }} />
        </div>
        <FormField label={t('company.logoFile')} error={f.logo} hint={t('company.logoHint')}>
          {(aria) => (
            <input
              {...aria}
              ref={fileRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              disabled={!canSave}
              className={`${FIELD_CLASS} h-auto py-1`}
              onChange={(e) => {
                const file = e.target.files?.[0] ?? null
                setLogo(file)
                setClearLogo(false)
                const problem = file ? logoProblem(file) : null
                setErrors(problem ? { fields: { logo: t(`company.logo.${problem}`) }, banner: undefined } : NO_ERRORS)
              }}
            />
          )}
        </FormField>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {logoUrl ? <img src={logoUrl} alt={t('company.currentLogo')} className="h-10 max-w-40 object-contain" /> : <span className="text-xs text-slate-500">{t('company.noLogo')}</span>}
        {logoUrl || logo ? (
          <WriteButton permission="company.update" onClick={() => { setLogo(null); setClearLogo(true); if (fileRef.current) fileRef.current.value = '' }}>{t('company.clearLogo')}</WriteButton>
        ) : null}
      </div>
      <p className="text-xs text-slate-500">{t('company.previewNote')}</p>
      <div className="flex justify-end">
        <WriteButton permission="company.update" variant="primary" type="submit" disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</WriteButton>
      </div>
    </form>
  )
}

/** Оформление: название, цвет, тема, логотип; предпросмотр до сохранения. */
export function BrandingBlock() {
  const { t } = useTranslation()
  const query = useQuery({ queryKey: ['company', 'branding'], queryFn: ({ signal }) => api.get<Branding>('/company/branding/', undefined, { signal }) })
  return (
    <section aria-labelledby="branding-title" className="space-y-2 rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <h2 id="branding-title" className="text-sm font-semibold">{t('company.branding')}</h2>
      {query.isError ? (
        <>
          <Banner kind="error">{errorMessage(query.error, t)}</Banner>
          <Button onClick={() => void query.refetch()}>{t('table.retry')}</Button>
        </>
      ) : query.data ? (
        <BrandingForm branding={query.data} />
      ) : (
        <Spinner label={t('table.loading')} />
      )}
    </section>
  )
}
