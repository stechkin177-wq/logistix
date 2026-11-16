import { useEffect, useRef, useState } from 'react'
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
import { PageHeader } from '../../shared/ui/PageHeader'
import { Download, Ellipsis, FileStack, ListChecks, RotateCcw, Upload } from '../../shared/ui/icons'

const ICON_BTN = 'inline-flex size-8 items-center justify-center rounded-control border border-line bg-surface text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50'

/** Меню «⋯» у строки: редкие действия (вернуть стартовую, отключить). Закрывается по клику вне и Esc. */
function RowMenu({ label, children }: { label: string; children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div ref={box} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label} className={ICON_BTN} onClick={() => { setOpen(!open) }}>
        <Ellipsis className="size-4" aria-hidden="true" />
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 flex w-52 flex-col gap-0.5 rounded-card border border-line bg-surface p-1 shadow-pop">
          {children(() => { setOpen(false) })}
        </div>
      ) : null}
    </div>
  )
}

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
            <tr className="text-left text-muted">
              <th scope="col" className="py-1 pr-3">{t('documents.templates.placeholderName')}</th>
              <th scope="col" className="py-1">{t('documents.templates.placeholderDescription')}</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((p) => (
              <tr key={p.name} className="border-t border-line">
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
        className={ICON_BTN}
        variant="ghost"
        disabled={upload.isPending}
        aria-label={upload.isPending ? t('documents.templates.uploading') : t('documents.templates.upload')}
        title={upload.isPending ? t('documents.templates.uploading') : t('documents.templates.upload')}
        onClick={() => { input.current?.click() }}
      >
        <Upload className="size-4" aria-hidden="true" />
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
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            className={ICON_BTN}
            disabled={downloading === r.id || r.current_version === null}
            aria-label={t('documents.templates.downloadNamed', { name: r.name })}
            title={t('documents.templates.download')}
            onClick={() => { void download(r) }}
          >
            <Download className="size-4" aria-hidden="true" />
          </Button>
          <UploadControl template={r} onError={setMessage} onDone={() => { setNotice(t('documents.templates.uploaded', { name: r.name })) }} />
          <Button
            variant="ghost"
            className={ICON_BTN}
            aria-label={t('documents.templates.placeholdersNamed', { name: r.name })}
            title={t('documents.templates.placeholders')}
            onClick={() => { setLabels(r) }}
          >
            <ListChecks className="size-4" aria-hidden="true" />
          </Button>
          <RowMenu label={t('documents.templates.more', { name: r.name })}>
            {(close) => (
              <>
                <WriteButton
                  variant="ghost"
                  permission="documents.update"
                  icon={RotateCcw}
                  className="w-full justify-start font-normal"
                  aria-label={t('documents.templates.resetNamed', { name: r.name })}
                  onClick={() => { close(); setResetting(r) }}
                >
                  {t('documents.templates.reset')}
                </WriteButton>
                <WriteButton
                  variant="ghost"
                  permission={r.is_active ? 'documents.delete' : 'documents.update'}
                  disabled={patch.isPending}
                  className="w-full justify-start font-normal"
                  aria-label={t(r.is_active ? 'documents.templates.disableNamed' : 'documents.templates.enableNamed', { name: r.name })}
                  onClick={() => { close(); toggle(r) }}
                >
                  {r.is_active ? t('documents.templates.disable') : t('documents.templates.enable')}
                </WriteButton>
              </>
            )}
          </RowMenu>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <PageHeader icon={FileStack} title={t('nav.doctemplates')} hint="doctemplates" />
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
