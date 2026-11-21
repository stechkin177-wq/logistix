import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Card, CardHeader } from '../../shared/ui/Card'
import { Checkbox } from '../../shared/ui/Checkbox'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { ScanText } from '../../shared/ui/icons'
import { useOcrSettings, useSaveOcrSettings, useGeminiModels, useTestGemini, useTestOcrSettings } from './hooks'
import type { OcrSettings } from './types'

function SettingsForm({ settings }: { settings: OcrSettings }) {
  const { t } = useTranslation()
  const save = useSaveOcrSettings()
  const test = useTestOcrSettings()
  const gemini = useTestGemini()
  const models = useGeminiModels()
  const [form, setForm] = useState({
    engine: settings.engine,
    auto_fallback: settings.auto_fallback,
    google_vision_key: '',
    ocr_space_key: '',
    gemini_key: '',
    handwriting_enabled: settings.handwriting_enabled,
    handwriting_crosscheck: settings.handwriting_crosscheck,
    handwriting_model: settings.handwriting_model,
    handwriting_check_model: settings.handwriting_check_model,
  })
  return (
    <Card>
      <CardHeader title={t('ocr.settingsCard')} />
      <form className="grid gap-3 p-4 sm:grid-cols-2" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate(form, { onSuccess: () => { setForm((f) => ({ ...f, google_vision_key: '', ocr_space_key: '', gemini_key: '' })) } }) }}>
        <Select label={t('ocr.mainEngine')} value={form.engine} options={settings.engines.map((e) => ({ value: e.code, label: e.code === 'tesseract' && !settings.tesseract_available ? `${e.label} (${t('ocr.unavailable')})` : e.label }))} onChange={(v) => { setForm({ ...form, engine: v }) }} />
        <Checkbox className="self-end" label={t('ocr.autoFallback')} checked={form.auto_fallback} onChange={(e) => { setForm({ ...form, auto_fallback: e.target.checked }) }} />
        <TextField label={t('ocr.googleKey')} type="password" autoComplete="new-password" value={form.google_vision_key} onChange={(e) => { setForm({ ...form, google_vision_key: e.target.value }) }} hint={settings.has_google_vision_key ? t('ocr.keyKept') : t('ocr.googleKeyHint')} />
        <TextField label={t('ocr.spaceKey')} type="password" autoComplete="new-password" value={form.ocr_space_key} onChange={(e) => { setForm({ ...form, ocr_space_key: e.target.value }) }} hint={settings.has_ocr_space_key ? t('ocr.keyKept') : t('ocr.spaceKeyHint')} />
        <div className="space-y-3 rounded-control border border-line bg-surface-2 p-3 sm:col-span-2">
          <h3 className="text-sm font-semibold">{t('ocr.gemini.title')}</h3>
          <p className="text-xs text-muted">{t('ocr.gemini.text')}</p>
          <Checkbox label={t('ocr.gemini.enabled')} checked={form.handwriting_enabled} onChange={(e) => { setForm({ ...form, handwriting_enabled: e.target.checked }) }} />
          <div className="grid gap-3 sm:grid-cols-3">
            <TextField label={t('ocr.gemini.key')} type="password" autoComplete="new-password" value={form.gemini_key} onChange={(e) => { setForm({ ...form, gemini_key: e.target.value }) }} hint={settings.has_gemini_key ? t('ocr.keyKept') : t('ocr.gemini.keyHint')} />
            <TextField label={t('ocr.gemini.model')} list="gemini-models" value={form.handwriting_model} onChange={(e) => { gemini.reset(); setForm({ ...form, handwriting_model: e.target.value }) }} />
            <TextField label={t('ocr.gemini.checkModel')} list="gemini-models" value={form.handwriting_check_model} onChange={(e) => { gemini.reset(); setForm({ ...form, handwriting_check_model: e.target.value }) }} />
          </div>
          <datalist id="gemini-models">{(models.data?.models ?? []).map((m) => <option key={m} value={m} />)}</datalist>
          <div className="flex flex-wrap items-center gap-2">
            <WriteButton permission="ocr.manage" disabled={models.isPending || !settings.has_gemini_key} onClick={() => { models.mutate() }}>{models.isPending ? t('ocr.testing') : t('ocr.gemini.loadModels')}</WriteButton>
            {models.data && models.data.models.length > 0 ? <WriteButton permission="ocr.manage" disabled={gemini.isPending} onClick={() => { gemini.mutate({ models: models.data.models.slice(0, 12) }) }}>{gemini.isPending ? t('ocr.testing') : t('ocr.gemini.testAll')}</WriteButton> : null}
            {models.data && models.data.models.length > 0 ? <span className="text-xs text-muted">{t('ocr.gemini.available', { list: models.data.models.slice(0, 8).join(', ') })}</span> : null}
          </div>
          {models.data?.error ? <Banner kind="error">{models.data.error}</Banner> : null}
          {models.isError ? <Banner kind="error">{errorMessage(models.error, t)}</Banner> : null}
          <Checkbox label={t('ocr.gemini.crosscheck')} checked={form.handwriting_crosscheck} onChange={(e) => { setForm({ ...form, handwriting_crosscheck: e.target.checked }) }} />
          {gemini.isError ? <Banner kind="error">{errorMessage(gemini.error, t)}</Banner> : null}
          {gemini.data?.error ? <Banner kind="error">{gemini.data.error}</Banner> : null}
          {gemini.data?.models ? Object.entries(gemini.data.models).sort(([, a], [, b]) => Number(b.ok) - Number(a.ok) || (a.seconds ?? 0) - (b.seconds ?? 0)).map(([model, r]) => (
            <Banner key={model} kind={r.ok ? 'info' : 'error'}>{r.ok ? t('ocr.gemini.testOk', { model, seconds: r.seconds ?? 0 }) : t('ocr.gemini.testFail', { model, error: r.error, seconds: r.seconds ?? 0 })}</Banner>
          )) : null}
          <WriteButton permission="ocr.manage" disabled={gemini.isPending || !settings.has_gemini_key} onClick={() => { gemini.mutate({ model: form.handwriting_model.trim(), check_model: form.handwriting_check_model.trim() }) }}>{gemini.isPending ? t('ocr.testing') : t('ocr.gemini.test')}</WriteButton>
        </div>
        <div className="space-y-2 sm:col-span-2">
          {settings.has_google_vision_key ? <p className="text-xs text-muted">{t('ocr.googleUsage', { used: settings.google_used, limit: settings.google_limit })}</p> : null}
          <p className="text-xs text-muted">{settings.storage_configured ? t('ocr.storageOn') : t('ocr.storageOff')}</p>
          {save.isError ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
          {save.isSuccess ? <Banner kind="info">{t('ocr.saved')}</Banner> : null}
          {test.isError ? <Banner kind="error">{errorMessage(test.error, t)}</Banner> : null}
          {test.data ? (
            Object.keys(test.data.results).length === 0 ? <Banner kind="error">{t('ocr.testNone')}</Banner> : Object.entries(test.data.results).map(([name, r]) => (
              <Banner key={name} kind={r.ok ? 'info' : 'error'}>{r.ok ? t('ocr.testOk', { name: t(`ocr.engines.${name}`, name) }) : t('ocr.testFail', { name: t(`ocr.engines.${name}`, name), error: r.error })}</Banner>
            ))
          ) : null}
          <div className="flex flex-wrap gap-2">
            <WriteButton type="submit" permission="ocr.manage" variant="primary" disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</WriteButton>
            <WriteButton permission="ocr.manage" disabled={test.isPending} onClick={() => { test.mutate() }}>{test.isPending ? t('ocr.testing') : t('ocr.test')}</WriteButton>
          </div>
        </div>
      </form>
    </Card>
  )
}

/** Настройки распознавания: основной движок, запасные варианты, ключи компании (хранятся зашифрованными). */
export function OcrSettingsPage() {
  const { t } = useTranslation()
  const settings = useOcrSettings()
  return (
    <div className="space-y-3">
      <PageHeader icon={ScanText} title={t('ocr.settingsTitle')} />
      {settings.isPending ? <Spinner /> : null}
      {settings.isError ? <Banner kind="error">{errorMessage(settings.error, t)}</Banner> : null}
      {settings.data ? <SettingsForm settings={settings.data} /> : null}
    </div>
  )
}
