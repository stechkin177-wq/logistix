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
import { useOcrSettings, useSaveOcrSettings, useTestOcrSettings } from './hooks'
import type { OcrSettings } from './types'

function SettingsForm({ settings }: { settings: OcrSettings }) {
  const { t } = useTranslation()
  const save = useSaveOcrSettings()
  const test = useTestOcrSettings()
  const [form, setForm] = useState({ engine: settings.engine, auto_fallback: settings.auto_fallback, google_vision_key: '', ocr_space_key: '' })
  return (
    <Card>
      <CardHeader title={t('ocr.settingsCard')} />
      <form className="grid gap-3 p-4 sm:grid-cols-2" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate(form, { onSuccess: () => { setForm((f) => ({ ...f, google_vision_key: '', ocr_space_key: '' })) } }) }}>
        <Select label={t('ocr.mainEngine')} value={form.engine} options={settings.engines.map((e) => ({ value: e.code, label: e.code === 'tesseract' && !settings.tesseract_available ? `${e.label} (${t('ocr.unavailable')})` : e.label }))} onChange={(v) => { setForm({ ...form, engine: v }) }} />
        <Checkbox className="self-end" label={t('ocr.autoFallback')} checked={form.auto_fallback} onChange={(e) => { setForm({ ...form, auto_fallback: e.target.checked }) }} />
        <TextField label={t('ocr.googleKey')} type="password" autoComplete="new-password" value={form.google_vision_key} onChange={(e) => { setForm({ ...form, google_vision_key: e.target.value }) }} hint={settings.has_google_vision_key ? t('ocr.keyKept') : t('ocr.googleKeyHint')} />
        <TextField label={t('ocr.spaceKey')} type="password" autoComplete="new-password" value={form.ocr_space_key} onChange={(e) => { setForm({ ...form, ocr_space_key: e.target.value }) }} hint={settings.has_ocr_space_key ? t('ocr.keyKept') : t('ocr.spaceKeyHint')} />
        <div className="space-y-2 sm:col-span-2">
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
