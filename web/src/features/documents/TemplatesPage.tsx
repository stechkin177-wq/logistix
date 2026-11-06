import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { Dialog } from '../../shared/ui/Dialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { WriteButton } from '../../shared/ui/WriteButton'
import { downloadTemplate, saveDownloaded } from './api'
import { usePatchTemplate, usePlaceholders, useResetTemplate, useTemplates, useUploadVersion } from './hooks'
import type { DocTemplate } from './types'

function PlaceholdersDialog({ template, onClose }: { template: DocTemplate; onClose: () => void }) {
  const { t } = useTranslation()
  const list = usePlaceholders(template.kind)
  return (
    <Dialog
      open
      title={t('documents.templates.placeholdersTitle', { name: t(`documents.kind.${template.kind}`) })}
      onClose={onClose}
      width="max-w-2xl"
      footer={<Button data-autofocus onClick={onClose}>{t('common.close')}</Button>}
    >
      {list.isError ? <Banner kind="error">{errorMessage(list.error, t)}</Banner> : null}
      {list.isPending ? <p className="text-sm">{t('common.loading')}</p> : null}
      {list.data ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{t('documents.templates.placeholders')}</caption>
          <thead>
            <tr className="text-left text-slate-500">
              <th scope="col" className="py-1 pr-3">{t('documents.templates.placeholderName')}</th>
              <th scope="col" className="py-1">{t('documents.templates.placeholderDescription')}</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((p) => (
              <tr key={p.name} className="border-t border-slate-200 dark:border-slate-700">
                <td className="py-1 pr-3 align-top"><code className="text-xs">{`{{ ${p.name} }}`}</code></td>
                <td className="py-1">{p.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Dialog>
  )
}

function UploadControl({ template, onError, onDone }: { template: DocTemplate; onError: (m: string) => void; onDone: () => void }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const upload = useUploadVersion()
  const choose = (file: File | undefined) => {
    if (!file) return
    onError('')
    upload.mutate(
      { id: template.id, file },
      { onSuccess: onDone, onError: (error) => { onError(errorMessage(error, t)) } },
    )
  }
  return (
    <>
      <WriteButton
        permission="documents.update"
        disabled={upload.isPending}
        onClick={() => { input.current?.click() }}
      >
        {upload.isPending ? t('documents.templates.uploading') : t('documents.templates.upload')}
      </WriteButton>
      <input
        ref={input}
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="sr-only"
        tabIndex={-1}
        aria-label={t('documents.templates.fileFor', { name: template.name })}
        onChange={(e) => {
          choose(e.target.files?.[0])
          e.target.value = ''
        }}
      />
    </>
  )
}

/** Настройки -> Шаблоны документов: скачать, загрузить новую версию, вернуть стартовую, метки, отключить. */
export function TemplatesPage() {
  const { t } = useTranslation()
  const list = useTemplates()
  const patch = usePatchTemplate()
  const reset = useResetTemplate()
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [labels, setLabels] = useState<DocTemplate | null>(null)
  const [resetting, setResetting] = useState<DocTemplate | null>(null)
  const [downloading, setDownloading] = useState<number | null>(null)

  const download = async (template: DocTemplate) => {
    setMessage('')
    setDownloading(template.id)
    try {
      await saveDownloaded(downloadTemplate(template.id), `${template.kind}-${template.language}.docx`)
    } catch (error) {
      setMessage(errorMessage(error, t))
    } finally {
      setDownloading(null)
    }
  }
  const toggle = (template: DocTemplate) => {
    setMessage('')
    patch.mutate(
      { id: template.id, body: { is_active: !template.is_active } },
      { onError: (error) => { setMessage(errorMessage(error, t)) } },
    )
  }

  const columns: Column<DocTemplate>[] = [
    { key: 'kind', header: t('documents.templates.kind'), cell: (r) => <span className="font-medium">{t(`documents.kind.${r.kind}`)}</span> },
    { key: 'name', header: t('documents.templates.name'), cell: (r) => r.name },
    { key: 'language', header: t('documents.templates.language'), cell: (r) => t(`documents.language.${r.language}`, { defaultValue: r.language }) },
    {
      key: 'version',
      header: t('documents.templates.version'),
      cell: (r) =>
        r.current_version ? (
          <span className="inline-flex items-center gap-1">
            {t('documents.templates.versionNumber', { number: r.current_version.number })}
            {r.current_version.is_starter ? <Badge tone="neutral">{t('documents.templates.starter')}</Badge> : null}
          </span>
        ) : '—',
    },
    {
      key: 'active',
      header: t('documents.templates.active'),
      cell: (r) => <Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('common.yes') : t('common.no')}</Badge>,
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      headerLabel: t('common.actions'),
      cell: (r) => (
        <div className="flex flex-wrap justify-end gap-1">
          <Button
            disabled={downloading === r.id || r.current_version === null}
            aria-label={t('documents.templates.downloadNamed', { name: r.name })}
            onClick={() => { void download(r) }}
          >
            {t('documents.templates.download')}
          </Button>
          <UploadControl template={r} onError={setMessage} onDone={() => { setNotice(t('documents.templates.uploaded', { name: r.name })) }} />
          <WriteButton permission="documents.update" aria-label={t('documents.templates.resetNamed', { name: r.name })} onClick={() => { setResetting(r) }}>
            {t('documents.templates.reset')}
          </WriteButton>
          <Button aria-label={t('documents.templates.placeholdersNamed', { name: r.name })} onClick={() => { setLabels(r) }}>
            {t('documents.templates.placeholders')}
          </Button>
          <WriteButton
            permission={r.is_active ? 'documents.delete' : 'documents.update'}
            disabled={patch.isPending}
            aria-label={t(r.is_active ? 'documents.templates.disableNamed' : 'documents.templates.enableNamed', { name: r.name })}
            onClick={() => { toggle(r) }}
          >
            {r.is_active ? t('documents.templates.disable') : t('documents.templates.enable')}
          </WriteButton>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div>
        <h1 className="text-base font-semibold">{t('nav.doctemplates')}</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">{t('documents.templates.hint')}</p>
      </div>
      {message ? <Banner kind="error">{message}</Banner> : null}
      {notice && !message ? <Banner kind="info">{notice}</Banner> : null}
      <DataTable
        caption={t('nav.doctemplates')}
        columns={columns}
        rows={list.data}
        rowKey={(r) => r.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('documents.templates.empty')} />}
      />
      {labels ? <PlaceholdersDialog template={labels} onClose={() => { setLabels(null) }} /> : null}
      <ConfirmDialog
        open={resetting !== null}
        title={t('documents.templates.resetTitle')}
        message={t('documents.templates.resetMessage', { name: resetting?.name ?? '' })}
        confirmLabel={t('documents.templates.reset')}
        busy={reset.isPending}
        error={reset.isError ? errorMessage(reset.error, t) : undefined}
        onCancel={() => { setResetting(null); reset.reset() }}
        onConfirm={() => {
          if (resetting) reset.mutate(resetting.id, { onSuccess: () => { setResetting(null); setNotice(t('documents.templates.resetDone', { name: resetting.name })) } })
        }}
      />
    </div>
  )
}
