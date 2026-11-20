import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card, CardHeader } from '../../shared/ui/Card'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateTime } from '../../shared/ui/DateTime'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { PageHeader } from '../../shared/ui/PageHeader'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { Trash2, Upload, ScanText } from '../../shared/ui/icons'
import { getOcrFileUrl } from './api'
import { SheetView } from './SheetView'
import { useDeleteOcr, useOcrDocuments, useUpdateOcr, useUploadOcr } from './hooks'
import { shrinkImage } from './image'
import { FUEL_TYPES, OCR_DOC_TYPES, OCR_FIELD_KEYS, type OcrDocType, type OcrDocument, type OcrFieldKey, type OcrStatus } from './types'

const STATUSES: OcrStatus[] = ['processing', 'done', 'failed']
const TONE = { processing: 'info', done: 'success', failed: 'danger' } as const
const SCHEMA = {
  q: codecs.string(''),
  status: codecs.oneOf(['', ...STATUSES] as const, ''),
  doc_type: codecs.oneOf(['', ...OCR_DOC_TYPES] as const, ''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}
const isDocType = (v: string): v is OcrDocType => (OCR_DOC_TYPES as string[]).includes(v)
/** Поля, показываемые в карточке: у чека АЗС расширенный набор, у остальных документов - дата, сумма, заметка. */
const fieldsFor = (type: OcrDocType): OcrFieldKey[] =>
  type === 'report_sheet' ? [] : type === 'fuel_receipt' ? [...OCR_FIELD_KEYS] : OCR_FIELD_KEYS.filter((k) => k === 'date' || k === 'amount' || k === 'note')

function UploadCard() {
  const { t } = useTranslation()
  const upload = useUploadOcr()
  const input = useRef<HTMLInputElement>(null)
  const [docType, setDocType] = useState<OcrDocType>('fuel_receipt')
  const [error, setError] = useState<string>()
  const onFile = async (file: File | undefined) => {
    if (!file) return
    setError(undefined)
    try {
      const { blob, name } = await shrinkImage(file)
      await upload.mutateAsync({ file: blob, name, docType })
    } catch (e) {
      setError(e instanceof Error && e.message === 'image_too_large' ? t('ocr.tooLarge') : errorMessage(e, t))
    } finally {
      if (input.current) input.current.value = ''
    }
  }
  return (
    <Card>
      <CardHeader title={t('ocr.uploadTitle')} />
      <div className="grid gap-3 p-4 sm:grid-cols-[minmax(0,16rem)_auto] sm:items-end">
        <Select label={t('ocr.docType')} value={docType} options={OCR_DOC_TYPES.map((v) => ({ value: v, label: t(`ocr.types.${v}`) }))} onChange={(v) => { if (isDocType(v)) setDocType(v) }} />
        <div>
          <input ref={input} type="file" accept="image/jpeg,image/png,image/*" capture="environment" className="sr-only" data-testid="ocr-file" aria-label={t('ocr.chooseFile')} onChange={(e) => { void onFile(e.target.files?.[0]) }} />
          <WriteButton permission="ocr.create" variant="primary" icon={Upload} disabled={upload.isPending} onClick={() => { input.current?.click() }}>
            {upload.isPending ? t('ocr.recognizing') : t('ocr.chooseFile')}
          </WriteButton>
        </div>
        <p className="text-xs text-muted sm:col-span-2">{t('ocr.uploadHint')}</p>
        {error ? <div className="sm:col-span-2"><Banner kind="error">{error}</Banner></div> : null}
        {upload.data?.status === 'failed' ? <div className="sm:col-span-2"><Banner kind="error">{t('ocr.failedBanner', { error: upload.data.error })}</Banner></div> : null}
      </div>
    </Card>
  )
}

function DocumentDrawer({ doc, onClose }: { doc: OcrDocument; onClose: () => void }) {
  const { t } = useTranslation()
  const update = useUpdateOcr()
  const remove = useDeleteOcr()
  const [docType, setDocType] = useState(doc.doc_type)
  const [values, setValues] = useState<Partial<Record<OcrFieldKey, string>>>(doc.fields)
  const [confirm, setConfirm] = useState(false)
  const [fileError, setFileError] = useState<string>()
  const isSheet = doc.doc_type === 'report_sheet'
  const keys = fieldsFor(docType)
  const set = (key: OcrFieldKey, value: string) => { setValues({ ...values, [key]: value }) }
  const save = () => {
    const fields: Partial<Record<OcrFieldKey, string>> = {}
    for (const key of keys) fields[key] = values[key] ?? ''
    update.mutate({ id: doc.id, body: { doc_type: docType, fields } }, { onSuccess: onClose })
  }
  const openOriginal = async () => {
    setFileError(undefined)
    try { window.open((await getOcrFileUrl(doc.id)).url, '_blank', 'noopener') } catch (e) { setFileError(errorMessage(e, t)) }
  }
  return (
    <Drawer
      open
      title={doc.original_name || t('ocr.document')}
      onClose={onClose}
      busy={update.isPending}
      footer={
        <>
          <WriteButton permission="ocr.delete" variant="dangerSoft" icon={Trash2} onClick={() => { setConfirm(true) }}>{t('common.delete')}</WriteButton>
          <Button onClick={onClose} disabled={update.isPending}>{t('common.cancel')}</Button>
          {isSheet ? null : <WriteButton permission="ocr.update" variant="primary" onClick={save} disabled={update.isPending}>{update.isPending ? t('common.saving') : t('common.save')}</WriteButton>}
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={TONE[doc.status]}>{t(`ocr.statuses.${doc.status}`)}</Badge>
          {doc.engine ? <span className="text-xs text-muted">{t('ocr.engine', { name: t(`ocr.engines.${doc.engine}`, doc.engine) })}</span> : null}
          {doc.has_file ? <Button onClick={() => { void openOriginal() }}>{t('ocr.openOriginal')}</Button> : null}
        </div>
        {fileError ? <Banner kind="error">{fileError}</Banner> : null}
        {doc.error ? <Banner kind="error">{doc.error}</Banner> : null}
        {update.isError ? <Banner kind="error">{errorMessage(update.error, t)}</Banner> : null}
        {isSheet ? <SheetView sheet={doc.sheet} /> : null}
        {isSheet ? null : <Select label={t('ocr.docType')} value={docType} options={OCR_DOC_TYPES.filter((v) => v !== 'report_sheet').map((v) => ({ value: v, label: t(`ocr.types.${v}`) }))} onChange={(v) => { if (isDocType(v)) setDocType(v) }} />}
        {isSheet ? null : <p className="text-xs text-muted">{t('ocr.fieldsHint')}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          {keys.map((key) =>
            key === 'fuel_type' ? (
              <Select key={key} label={t('ocr.fields.fuel_type')} value={values.fuel_type ?? ''} placeholder="-" options={FUEL_TYPES.map((v) => ({ value: v, label: t(`ocr.fuel.${v}`) }))} onChange={(v) => { set('fuel_type', v) }} />
            ) : (
              <TextField key={key} label={t(`ocr.fields.${key}`)} value={values[key] ?? ''} maxLength={200} onChange={(e) => { set(key, e.target.value) }} hint={key === 'date' ? t('ocr.dateHint') : undefined} />
            ),
          )}
        </div>
        {isSheet ? null : <TextArea label={t('ocr.text')} value={doc.text} readOnly rows={8} />}
      </div>
      <ConfirmDialog
        open={confirm}
        danger
        title={t('ocr.deleteTitle')}
        message={t('ocr.deleteMessage', { name: doc.original_name })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setConfirm(false); remove.reset() }}
        onConfirm={() => { remove.mutate(doc.id, { onSuccess: onClose }) }}
      />
    </Drawer>
  )
}

/** Распознавание документов: загрузка фото чека/накладной, поля находятся сами и правятся человеком. */
export function OcrPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useOcrDocuments({ page: state.page, q: state.q, status: state.status, doc_type: state.doc_type })
  const [open, setOpen] = useState<{ doc: OcrDocument; nonce: number } | null>(null)
  const columns: Column<OcrDocument>[] = [
    { key: 'when', header: t('ocr.when'), cell: (d) => <DateTime value={d.created_at} /> },
    {
      key: 'name',
      header: t('ocr.file'),
      cell: (d) => <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setOpen({ doc: d, nonce: Date.now() }) }}>{d.original_name || t('ocr.document')}</button>,
    },
    { key: 'type', header: t('ocr.docType'), cell: (d) => t(`ocr.types.${d.doc_type}`) },
    { key: 'status', header: t('common.status'), cell: (d) => <Badge tone={TONE[d.status]}>{t(`ocr.statuses.${d.status}`)}</Badge> },
    { key: 'amount', header: t('ocr.fields.amount'), align: 'right', cell: (d) => d.fields.amount ?? '' },
    { key: 'by', header: t('ocr.uploadedBy'), cell: (d) => d.uploaded_by_name },
  ]
  const filtered = state.q !== '' || state.status !== '' || state.doc_type !== ''
  return (
    <div className="space-y-3">
      <PageHeader
        icon={ScanText}
        title={t('ocr.title')}
        hint="ocr"
        actions={<Link className="text-sm text-brand-700 hover:underline dark:text-brand-300" to="/settings/ocr">{t('ocr.settingsLink')}</Link>}
      />
      <UploadCard />
      <FilterBar
        search={<FilterItem className="w-auto"><TextField label={t('common.search')} type="search" placeholder={t('ocr.search')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} /></FilterItem>}
        canReset={filtered}
        onReset={() => { setState({ q: '', status: '', doc_type: '' }) }}
      >
        <FilterItem>
          <Select label={t('common.status')} value={state.status} placeholder={t('common.all')} options={STATUSES.map((v) => ({ value: v, label: t(`ocr.statuses.${v}`) }))} onChange={(v) => { setState({ status: STATUSES.find((s) => s === v) ?? '' }) }} />
        </FilterItem>
        <FilterItem>
          <Select label={t('ocr.docType')} value={state.doc_type} placeholder={t('common.all')} options={OCR_DOC_TYPES.map((v) => ({ value: v, label: t(`ocr.types.${v}`) }))} onChange={(v) => { setState({ doc_type: OCR_DOC_TYPES.find((s) => s === v) ?? '' }) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('ocr.title')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(d) => d.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        onRowClick={(d) => { setOpen({ doc: d, nonce: Date.now() }) }}
        empty={<EmptyState title={t('ocr.empty')} hint={t('ocr.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {open ? <DocumentDrawer key={open.nonce} doc={open.doc} onClose={() => { setOpen(null) }} /> : null}
    </div>
  )
}
