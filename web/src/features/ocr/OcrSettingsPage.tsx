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
import { Plus, ScanText, Trash2 } from '../../shared/ui/icons'
import { useCreateOcrDocType, useDeleteOcrDocType, useOcrDocTypes, useOcrSettings, useSaveOcrSettings, useTestOcrSettings, useUpdateOcrDocType } from './hooks'
import type { OcrDocTypeRow, OcrSettings } from './types'

const GEMINI_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash']
const HANDLERS = ['receipt', 'sheet', 'generic'] as const

function DocTypeRow({ row }: { row: OcrDocTypeRow }) {
  const { t } = useTranslation()
  const update = useUpdateOcrDocType()
  const remove = useDeleteOcrDocType()
  const [name, setName] = useState(row.name)
  const patch = (body: Parameters<typeof update.mutate>[0]['body']) => { update.mutate({ id: row.id, body }) }
  return (
    <li className={`grid gap-2 border-t border-line p-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto_auto_auto] sm:items-end ${row.is_active ? '' : 'opacity-60'}`} data-testid="doctype-row">
      <TextField label={t('ocr.types_.name')} value={name} maxLength={100} onChange={(e) => { setName(e.target.value) }} onBlur={() => { if (name.trim() && name.trim() !== row.name) patch({ name: name.trim() }) }} />
      <Select label={t('ocr.types_.handler')} value={row.handler} options={HANDLERS.map((h) => ({ value: h, label: t(`ocr.types_.handlers.${h}`) }))} onChange={(v) => { const h = HANDLERS.find((x) => x === v); if (h) patch({ handler: h }) }} />
      <Checkbox label={t('ocr.types_.driverVisible')} checked={row.driver_visible} onChange={(e) => { patch({ driver_visible: e.target.checked }) }} />
      <Checkbox label={t('ocr.types_.active')} checked={row.is_active} onChange={(e) => { patch({ is_active: e.target.checked }) }} />
      <WriteButton permission="ocr.manage" variant="dangerSoft" icon={Trash2} aria-label={t('common.delete')} disabled={remove.isPending} onClick={() => { remove.mutate(row.id) }} />
      {update.isError ? <div className="sm:col-span-5"><Banner kind="error">{errorMessage(update.error, t)}</Banner></div> : null}
      {remove.data?.deactivated ? <p className="text-xs text-muted sm:col-span-5">{t('ocr.types_.deactivated')}</p> : null}
    </li>
  )
}

/** Список типов документов компании: что видит водитель и как читается документ. */
function DocTypesCard() {
  const { t } = useTranslation()
  const types = useOcrDocTypes()
  const create = useCreateOcrDocType()
  const [name, setName] = useState('')
  const [handler, setHandler] = useState<(typeof HANDLERS)[number]>('generic')
  return (
    <Card>
      <CardHeader title={t('ocr.types_.title')} />
      <p className="px-4 pt-3 text-xs text-muted">{t('ocr.types_.hint')}</p>
      {types.isError ? <div className="p-4"><Banner kind="error">{errorMessage(types.error, t)}</Banner></div> : null}
      <ul>{(types.data ?? []).map((row) => <DocTypeRow key={`${String(row.id)}-${row.name}-${row.handler}-${String(row.driver_visible)}-${String(row.is_active)}`} row={row} />)}</ul>
      <form className="grid gap-2 border-t border-line p-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-end" noValidate onSubmit={(e) => { e.preventDefault(); if (!name.trim()) return; create.mutate({ name: name.trim(), handler, driver_visible: true }, { onSuccess: () => { setName('') } }) }}>
        <TextField label={t('ocr.types_.newName')} value={name} maxLength={100} onChange={(e) => { setName(e.target.value) }} />
        <Select label={t('ocr.types_.handler')} value={handler} options={HANDLERS.map((h) => ({ value: h, label: t(`ocr.types_.handlers.${h}`) }))} onChange={(v) => { const h = HANDLERS.find((x) => x === v); if (h) setHandler(h) }} />
        <WriteButton type="submit" permission="ocr.manage" variant="primary" icon={Plus} disabled={create.isPending || !name.trim()}>{t('ocr.types_.add')}</WriteButton>
        {create.isError ? <div className="sm:col-span-3"><Banner kind="error">{errorMessage(create.error, t)}</Banner></div> : null}
      </form>
    </Card>
  )
}

function SettingsForm({ settings }: { settings: OcrSettings }) {
  const { t } = useTranslation()
  const save = useSaveOcrSettings()
  const test = useTestOcrSettings()
  const [form, setForm] = useState({
    engine: settings.engine,
    auto_fallback: settings.auto_fallback,
    google_vision_key: '',
    ocr_space_key: '',
    gemini_key: '',
    handwriting_enabled: settings.handwriting_enabled,
    handwriting_crosscheck: settings.handwriting_crosscheck,
    handwriting_model: settings.handwriting_model,
  })
  return (
    <Card>
      <CardHeader title={t('ocr.settingsCard')} />
      <form className="grid gap-3 p-4 sm:grid-cols-2" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate(form, { onSuccess: () => { setForm((f) => ({ ...f, google_vision_key: '', ocr_space_key: '', gemini_key: '' })) } }) }}>
        <Select label={t('ocr.mainEngine')} value={form.engine} options={settings.engines.map((e) => ({ value: e.code, label: e.code === 'tesseract' && !settings.tesseract_available ? `${e.label} (${t('ocr.unavailable')})` : e.label }))} onChange={(v) => { setForm({ ...form, engine: v }) }} />
        <Checkbox className="self-end" label={t('ocr.autoFallback')} checked={form.auto_fallback} onChange={(e) => { setForm({ ...form, auto_fallback: e.target.checked }) }} />
        <TextField label={t('ocr.gemini.key')} type="password" autoComplete="new-password" value={form.gemini_key} onChange={(e) => { setForm({ ...form, gemini_key: e.target.value }) }} hint={settings.has_gemini_key ? t('ocr.keyKept') : t('ocr.gemini.keyHint')} />
        <TextField label={t('ocr.spaceKey')} type="password" autoComplete="new-password" value={form.ocr_space_key} onChange={(e) => { setForm({ ...form, ocr_space_key: e.target.value }) }} hint={settings.has_ocr_space_key ? t('ocr.keyKept') : t('ocr.spaceKeyHint')} />
        <TextField label={t('ocr.googleKey')} type="password" autoComplete="new-password" value={form.google_vision_key} onChange={(e) => { setForm({ ...form, google_vision_key: e.target.value }) }} hint={settings.has_google_vision_key ? t('ocr.keyKept') : t('ocr.googleKeyHint')} />
        <div className="space-y-3 rounded-control border border-line bg-surface-2 p-3 sm:col-span-2">
          <h3 className="text-sm font-semibold">{t('ocr.gemini.title')}</h3>
          <p className="text-xs text-muted">{t('ocr.gemini.text')}</p>
          <Checkbox label={t('ocr.gemini.enabled')} checked={form.handwriting_enabled} onChange={(e) => { setForm({ ...form, handwriting_enabled: e.target.checked }) }} />
          <TextField label={t('ocr.gemini.model')} list="gemini-models" value={form.handwriting_model} onChange={(e) => { setForm({ ...form, handwriting_model: e.target.value }) }} hint={t('ocr.gemini.modelHint')} />
          <datalist id="gemini-models">{GEMINI_MODELS.map((m) => <option key={m} value={m} />)}</datalist>
          <Checkbox label={t('ocr.gemini.crosscheck')} checked={form.handwriting_crosscheck} onChange={(e) => { setForm({ ...form, handwriting_crosscheck: e.target.checked }) }} />
        </div>
        <div className="space-y-2 sm:col-span-2">
          {settings.has_google_vision_key ? <p className="text-xs text-muted">{t('ocr.googleUsage', { used: settings.google_used, limit: settings.google_limit })}</p> : null}
          <p className="text-xs text-muted">{t('ocr.storageDb', { days: 180 })}</p>
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
      {settings.data ? <DocTypesCard /> : null}
    </div>
  )
}
