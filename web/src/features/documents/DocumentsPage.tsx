import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Banner } from '../../shared/ui/Banner'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useIssued } from './hooks'
import { DownloadButtons, IssuedDialog } from './IssuedDialog'
import { LetterDrawer } from './LetterDrawer'
import { DOCUMENT_KINDS, type IssuedDocument, type IssuedFilters } from './types'

const KIND_VALUES = ['', ...DOCUMENT_KINDS] as const

export const ISSUED_SCHEMA = {
  kind: codecs.oneOf(KIND_VALUES, ''),
  date_from: codecs.date(),
  date_to: codecs.date(),
  search: codecs.string(''),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
}

const LINK = 'text-brand-700 underline dark:text-brand-300'

function Sources({ doc }: { doc: IssuedDocument }) {
  const links = [
    doc.invoice ? <Link key="invoice" className={LINK} to={`/finance/invoices/${String(doc.invoice.id)}`}>{doc.invoice.number}</Link> : null,
    doc.order ? <Link key="order" className={LINK} to={`/orders/${String(doc.order.id)}`}>{doc.order.number}</Link> : null,
    doc.trip ? <Link key="trip" className={LINK} to={`/trips?q=${encodeURIComponent(doc.trip.number)}`}>{doc.trip.number}</Link> : null,
    doc.client ? <Link key="client" className={LINK} to={`/clients?q=${encodeURIComponent(doc.client.name)}`}>{doc.client.name}</Link> : null,
  ].filter((x) => x !== null)
  if (links.length === 0) return <>—</>
  return (
    <span className="inline-flex flex-wrap gap-x-2">
      {links.map((link, i) => <span key={link.key}>{i > 0 ? '· ' : ''}{link}</span>)}
    </span>
  )
}

/** Журнал выданных документов: фильтры в адресе, скачивание DOCX/PDF, письмо на бланке. */
export function DocumentsPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(ISSUED_SCHEMA, { pageKey: 'page' })
  const filters: IssuedFilters = state
  const list = useIssued(filters)
  const [letterOpen, setLetterOpen] = useState(false)
  const [issued, setIssued] = useState<IssuedDocument | null>(null)
  const [downloadError, setDownloadError] = useState('')

  const columns: Column<IssuedDocument>[] = [
    { key: 'date', header: t('documents.issued.date'), cell: (d) => <DateTime value={d.issue_date} dateOnly /> },
    { key: 'kind', header: t('documents.issued.kind'), cell: (d) => t(`documents.kind.${d.kind}`) },
    { key: 'number', header: t('documents.issued.number'), cell: (d) => <span className="font-medium">{d.number}</span> },
    { key: 'source', header: t('documents.issued.source'), cell: (d) => <Sources doc={d} /> },
    { key: 'by', header: t('documents.issued.createdBy'), cell: (d) => d.created_by?.full_name ?? '—' },
    {
      key: 'files',
      header: <span className="sr-only">{t('documents.issued.files')}</span>,
      headerLabel: t('documents.issued.files'),
      cell: (d) => <div className="flex justify-end gap-1"><DownloadButtons doc={d} onError={setDownloadError} /></div>,
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.documents')}</h1>
        <WriteButton variant="primary" permission="documents.create" onClick={() => { setLetterOpen(true) }}>
          {t('documents.letter.open')}
        </WriteButton>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label={t('documents.issued.kind')}
          value={state.kind}
          placeholder={t('documents.issued.allKinds')}
          options={DOCUMENT_KINDS.map((k) => ({ value: k, label: t(`documents.kind.${k}`) }))}
          onChange={(value) => { setState({ kind: value as typeof state.kind }) }}
        />
        <DateInput label={t('documents.issued.dateFrom')} value={state.date_from} onChange={(value) => { setState({ date_from: value }) }} />
        <DateInput label={t('documents.issued.dateTo')} value={state.date_to} onChange={(value) => { setState({ date_to: value }) }} />
        <TextField label={t('documents.issued.search')} value={state.search} onChange={(e) => { setState({ search: e.target.value }) }} />
      </div>
      {downloadError ? <Banner kind="error">{downloadError}</Banner> : null}
      <DataTable
        caption={t('nav.documents')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(d) => d.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState title={t('documents.issued.empty')} hint={t('documents.issued.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {letterOpen ? (
        <LetterDrawer
          onClose={() => { setLetterOpen(false) }}
          onIssued={(doc) => { setLetterOpen(false); setIssued(doc) }}
        />
      ) : null}
      {issued ? <IssuedDialog doc={issued} onClose={() => { setIssued(null) }} /> : null}
    </div>
  )
}
