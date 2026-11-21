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
import { SegmentedControl } from '../../shared/ui/SegmentedControl'
import { Tabs } from '../../shared/ui/Tabs'
import { Archive, ArchiveRestore, Eye, ScanText, Trash2, Upload } from '../../shared/ui/icons'
import { getOcrImage } from './api'
import { PhotoDialog } from './ImageViewer'
import { ReviewScreen } from './ReviewScreen'
import { SheetView } from './SheetView'
import { useArchiveOcr, useDeleteOcr, useOcrDocTypes, useOcrDocuments, useOcrGroups, useReviewOcr, useUpdateOcr, useUploadOcr } from './hooks'
import { shrinkImage } from './image'
import { FUEL_TYPES, OCR_FIELD_KEYS, type OcrDocType, type OcrDocTypeRow, type OcrDocument, type OcrFieldKey, type OcrGroup, type OcrStatus } from './types'

const STATUSES: OcrStatus[] = ['processing', 'done', 'failed']
const TONE = { processing: 'info', done: 'success', failed: 'danger' } as const
const SCHEMA = {
  q: codecs.string(''),
  status: codecs.oneOf(['', ...STATUSES] as const, ''),
  doc_type: codecs.string(''),
  tab: codecs.oneOf(['docs', 'archive'] as const, 'docs'),
  by: codecs.oneOf(['driver', 'vehicle', 'all'] as const, 'driver'),
  group: codecs.string(''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}
/** Поля, показываемые в карточке: у чека АЗС расширенный набор, у остальных документов - дата, сумма, заметка. */
const fieldsFor = (handler: string): OcrFieldKey[] =>
  handler === 'sheet' ? [] : handler === 'receipt' ? [...OCR_FIELD_KEYS] : OCR_FIELD_KEYS.filter((k) => k === 'date' || k === 'amount' || k === 'note')

function UploadCard() {
  const { t } = useTranslation()
  const upload = useUploadOcr()
  const input = useRef<HTMLInputElement>(null)
  const types = useOcrDocTypes()
  const options = (types.data ?? []).filter((x) => x.is_active)
  const [docType, setDocType] = useState<OcrDocType>('')
  const effective = options.some((o) => o.code === docType) ? docType : (options[0]?.code ?? '')
  const [error, setError] = useState<string>()
  const onFile = async (file: File | undefined) => {
    if (!file) return
    setError(undefined)
    try {
      const { blob, name } = await shrinkImage(file)
      await upload.mutateAsync({ file: blob, name, docType: effective })
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
        <Select label={t('ocr.docType')} value={effective} options={options.map((o) => ({ value: o.code, label: o.name }))} onChange={setDocType} />
        <div>
          <input ref={input} type="file" accept="image/jpeg,image/png,image/*" capture="environment" className="sr-only" data-testid="ocr-file" aria-label={t('ocr.chooseFile')} onChange={(e) => { void onFile(e.target.files?.[0]) }} />
          <WriteButton permission="ocr.create" variant="primary" icon={Upload} disabled={upload.isPending || effective === ''} onClick={() => { input.current?.click() }}>
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

function DocumentDrawer({ doc, types, onClose }: { doc: OcrDocument; types: OcrDocTypeRow[]; onClose: () => void }) {
  const { t } = useTranslation()
  const archive = useArchiveOcr()
  const [photo, setPhoto] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const update = useUpdateOcr()
  const remove = useDeleteOcr()
  const review = useReviewOcr()
  const [docType, setDocType] = useState(doc.doc_type)
  const [values, setValues] = useState<Partial<Record<OcrFieldKey, string>>>(doc.fields)
  const [confirm, setConfirm] = useState(false)
  const handlerOf = (code: string) => types.find((x) => x.code === code)?.handler ?? 'generic'
  const isSheet = handlerOf(doc.doc_type) === 'sheet'
  const keys = fieldsFor(handlerOf(docType))
  const set = (key: OcrFieldKey, value: string) => { setValues({ ...values, [key]: value }) }
  const save = () => {
    const fields: Partial<Record<OcrFieldKey, string>> = {}
    for (const key of keys) fields[key] = values[key] ?? ''
    update.mutate({ id: doc.id, body: { doc_type: docType, fields } }, { onSuccess: onClose })
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
          {doc.has_file ? <Button icon={Eye} onClick={() => { setPhoto(true) }}>{t('ocr.openOriginal')}</Button> : <span className="text-xs text-muted">{t('ocr.noPhoto')}</span>}
          {isSheet && doc.has_file && doc.status === 'done' ? <WriteButton permission="ocr.update" variant="primary" onClick={() => { setReviewing(true) }}>{t('ocr.review_.open')}</WriteButton> : null}
          <WriteButton permission="ocr.update" icon={doc.archived_at ? ArchiveRestore : Archive} disabled={archive.isPending} onClick={() => { archive.mutate({ id: doc.id, archived: !doc.archived_at }, { onSuccess: onClose }) }}>{doc.archived_at ? t('ocr.restore') : t('ocr.toArchive')}</WriteButton>
        </div>
        {doc.source === 'driver_app' ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-surface-2 px-3 py-2 text-sm">
            <span>{t('ocr.fromDriver', { driver: doc.driver_name || '-', trip: doc.trip_number || t('ocr.noTrip') })}{doc.route ? ` · ${doc.route}` : ''}{doc.vehicle_plate ? ` · ${doc.vehicle_plate}` : ''}</span>
            <WriteButton permission="ocr.update" disabled={review.isPending} onClick={() => { review.mutate({ id: doc.id, reviewed: doc.reviewed_at === null }, { onSuccess: onClose }) }}>
              {doc.reviewed_at === null ? t('ocr.markReviewed') : t('ocr.unmarkReviewed')}
            </WriteButton>
          </div>
        ) : null}
        {doc.error ? <Banner kind="error">{doc.error}</Banner> : null}
        {update.isError ? <Banner kind="error">{errorMessage(update.error, t)}</Banner> : null}
        {isSheet ? <SheetView sheet={doc.sheet} /> : null}
        {isSheet ? null : <Select label={t('ocr.docType')} value={docType} options={types.filter((x) => (x.is_active || x.code === docType) && x.handler !== 'sheet').map((x) => ({ value: x.code, label: x.name }))} onChange={setDocType} />}
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
      {photo ? <PhotoDialog title={doc.doc_type_name} name={doc.original_name} queryKey={['ocr', 'image', doc.id]} load={() => getOcrImage(doc.id)} onClose={() => { setPhoto(false) }} /> : null}
      {reviewing ? <ReviewScreen doc={doc} onClose={() => { setReviewing(false); onClose() }} /> : null}
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

/** Список групп (водители или машины) с числом документов и ожидающих проверки. */
function GroupList({ by, groups, selected, onSelect }: { by: 'driver' | 'vehicle'; groups: OcrGroup[]; selected: number | null; onSelect: (id: number) => void }) {
  const { t } = useTranslation()
  return (
    <nav aria-label={t(by === 'driver' ? 'ocr.groups.drivers' : 'ocr.groups.vehicles')} className="thin-scroll flex gap-1 overflow-x-auto md:max-h-[60vh] md:flex-col md:overflow-y-auto" data-testid="ocr-groups">
      {groups.map((g) => (
        <button
          key={g.id}
          type="button"
          aria-current={selected === g.id}
          onClick={() => { onSelect(g.id) }}
          className={`flex shrink-0 items-center justify-between gap-2 rounded-control border px-3 py-2 text-left text-sm ${selected === g.id ? 'border-brand-600 bg-brand-50 font-medium dark:bg-white/10' : 'border-line bg-surface hover:bg-surface-2'}`}
        >
          <span className="truncate">{g.name || t(by === 'driver' ? 'ocr.groups.noDriver' : 'ocr.groups.noVehicle')}</span>
          <span className="flex shrink-0 items-center gap-1">
            {g.pending > 0 ? <Badge tone="warning">{g.pending}</Badge> : null}
            <span className="text-xs text-muted">{g.total}</span>
          </span>
        </button>
      ))}
    </nav>
  )
}

/** Распознавание документов: документы разделены по водителям или по машинам, вкладка «Архив»,
 * сверка рукописного листа с фото. */
export function OcrPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const archived = state.tab === 'archive'
  const grouped = state.by !== 'all'
  const types = useOcrDocTypes()
  const groups = useOcrGroups(state.by === 'vehicle' ? 'vehicle' : 'driver', archived, grouped)
  const groupList = groups.data?.results ?? []
  const picked = /^\d+$/.test(state.group) ? Number(state.group) : null
  const selected = grouped ? (groupList.some((g) => g.id === picked) ? picked : (groupList[0]?.id ?? null)) : null
  const ready = !grouped || (!groups.isPending && (selected !== null || groupList.length === 0))
  const list = useOcrDocuments({
    page: state.page, q: state.q, status: state.status, doc_type: state.doc_type, archived,
    driver: state.by === 'driver' && selected !== null ? selected : undefined,
    vehicle: state.by === 'vehicle' && selected !== null ? selected : undefined,
  }, ready && !(grouped && selected === null))
  const [open, setOpen] = useState<{ doc: OcrDocument; nonce: number } | null>(null)
  const typeRows = types.data ?? []
  const columns: Column<OcrDocument>[] = [
    { key: 'when', header: t('ocr.when'), cell: (d) => <DateTime value={d.created_at} /> },
    {
      key: 'name',
      header: t('ocr.docType'),
      cell: (d) => <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setOpen({ doc: d, nonce: Date.now() }) }}>{d.doc_type_name || t('ocr.document')}</button>,
    },
    { key: 'status', header: t('common.status'), cell: (d) => <Badge tone={TONE[d.status]}>{t(`ocr.statuses.${d.status}`)}</Badge> },
    { key: 'amount', header: t('ocr.fields.amount'), align: 'right', cell: (d) => d.fields.amount ?? '' },
    { key: 'trip', header: t('ocr.trip'), cell: (d) => d.trip_number },
    { key: 'route', header: t('ocr.route'), cell: (d) => d.route },
    ...(state.by === 'driver' ? [] : [{ key: 'driver', header: t('ocr.driver'), cell: (d: OcrDocument) => d.driver_name || d.uploaded_by_name }]),
    ...(state.by === 'vehicle' ? [] : [{ key: 'vehicle', header: t('ocr.vehicle'), cell: (d: OcrDocument) => d.vehicle_plate }]),
    { key: 'review', header: t('ocr.review'), cell: (d) => (d.source === 'driver_app' ? <Badge tone={d.reviewed_at ? 'success' : 'warning'}>{d.reviewed_at ? t('ocr.reviewed') : t('ocr.toReview')}</Badge> : null) },
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
      <Tabs variant="pills" label={t('ocr.title')} active={state.tab} onChange={(k) => { setState({ tab: k === 'archive' ? 'archive' : 'docs', group: '', page: 1 }) }} tabs={[{ key: 'docs', label: t('ocr.tabs.docs') }, { key: 'archive', label: t('ocr.tabs.archive'), icon: Archive }]} />
      {archived ? <p className="text-xs text-muted">{t('ocr.archiveHint', { days: 180 })}</p> : <UploadCard />}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl label={t('ocr.groups.by')} value={state.by} options={[{ value: 'driver', label: t('ocr.groups.drivers') }, { value: 'vehicle', label: t('ocr.groups.vehicles') }, { value: 'all', label: t('ocr.groups.all') }]} onChange={(v) => { setState({ by: v === 'vehicle' ? 'vehicle' : v === 'all' ? 'all' : 'driver', group: '', page: 1 }) }} />
      </div>
      <div className={grouped ? 'grid gap-3 md:grid-cols-[16rem_minmax(0,1fr)]' : 'space-y-3'}>
        {grouped ? (
          <div>
            {groups.isError ? <Banner kind="error">{errorMessage(groups.error, t)}</Banner> : null}
            {groupList.length === 0 && !groups.isPending ? <p className="text-sm text-muted">{t('ocr.groups.empty')}</p> : null}
            <GroupList by={state.by === 'vehicle' ? 'vehicle' : 'driver'} groups={groupList} selected={selected} onSelect={(id) => { setState({ group: String(id), page: 1 }) }} />
          </div>
        ) : null}
        <div className="min-w-0 space-y-3">
          <FilterBar
            search={<FilterItem className="w-auto"><TextField label={t('common.search')} type="search" placeholder={t('ocr.search')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} /></FilterItem>}
            canReset={filtered}
            onReset={() => { setState({ q: '', status: '', doc_type: '' }) }}
          >
            <FilterItem>
              <Select label={t('common.status')} value={state.status} placeholder={t('common.all')} options={STATUSES.map((v) => ({ value: v, label: t(`ocr.statuses.${v}`) }))} onChange={(v) => { setState({ status: STATUSES.find((s) => s === v) ?? '' }) }} />
            </FilterItem>
            <FilterItem>
              <Select label={t('ocr.docType')} value={state.doc_type} placeholder={t('common.all')} options={typeRows.map((x) => ({ value: x.code, label: x.name }))} onChange={(v) => { setState({ doc_type: v }) }} />
            </FilterItem>
          </FilterBar>
          <DataTable
            caption={t('ocr.title')}
            columns={columns}
            rows={grouped && selected === null ? [] : list.data?.results}
            rowKey={(d) => d.id}
            loading={list.isFetching}
            error={list.isError ? errorMessage(list.error, t) : undefined}
            onRetry={() => void list.refetch()}
            onRowClick={(d) => { setOpen({ doc: d, nonce: Date.now() }) }}
            empty={<EmptyState title={archived ? t('ocr.archiveEmpty') : t('ocr.empty')} hint={archived ? undefined : t('ocr.emptyHint')} />}
          />
          <Pagination page={state.page} pageSize={state.pageSize} count={grouped && selected === null ? 0 : (list.data?.count ?? 0)} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
        </div>
      </div>
      {open ? <DocumentDrawer key={open.nonce} doc={open.doc} types={typeRows} onClose={() => { setOpen(null) }} /> : null}
    </div>
  )
}
