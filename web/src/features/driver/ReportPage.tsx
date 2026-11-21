import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card } from '../../shared/ui/Card'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { Tabs } from '../../shared/ui/Tabs'
import { Archive, ArchiveRestore, Camera, Eye, Paperclip } from '../../shared/ui/icons'
import { PhotoDialog } from '../ocr/ImageViewer'
import { shrinkImage } from '../ocr/image'
import type { OcrDocument } from '../ocr/types'
import { getDriverReportImage } from './api'
import { useArchiveReport, useDriverReportTypes, useDriverReports, useDriverTrips, useSendReport } from './hooks'

function ReportCard({ doc, archived }: { doc: OcrDocument; archived: boolean }) {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const archive = useArchiveReport()
  const [photo, setPhoto] = useState(false)
  return (
    <Card className="space-y-2 p-3" data-testid="report-card">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{doc.doc_type_name}</p>
          <p className="text-xs text-muted">{dateTime(doc.created_at)}</p>
          {doc.trip_number ? <p className="text-xs text-muted">{t('driver.report.tripNo', { number: doc.trip_number })}{doc.route ? ` · ${doc.route}` : ''}</p> : null}
        </div>
        <Badge tone={doc.status === 'failed' ? 'danger' : 'success'}>{doc.status === 'failed' ? t('ocr.statuses.failed') : t('driver.report.sent')}</Badge>
      </div>
      {doc.status === 'failed' ? <Banner kind="error">{doc.error}</Banner> : null}
      <div className="flex flex-wrap gap-2">
        {doc.has_file ? <Button icon={Eye} onClick={() => { setPhoto(true) }}>{t('driver.report.viewFile')}</Button> : <span className="self-center text-xs text-muted">{t('driver.report.noFile')}</span>}
        <Button icon={archived ? ArchiveRestore : Archive} disabled={archive.isPending} onClick={() => { archive.mutate({ id: doc.id, archived: !archived }) }}>
          {archived ? t('driver.report.restore') : t('driver.report.toArchive')}
        </Button>
      </div>
      {archive.isError ? <Banner kind="error">{errorMessage(archive.error, t)}</Banner> : null}
      {photo ? <PhotoDialog title={doc.doc_type_name} name={doc.original_name} queryKey={['driver', 'report-image', doc.id]} load={() => getDriverReportImage(doc.id)} onClose={() => { setPhoto(false) }} /> : null}
    </Card>
  )
}

/** Вкладка «Отчёт»: фото рукописного листа, чека или документа; распознаётся сразу, сомнительные
 * значения подсвечены; отправка в офис происходит самой загрузкой, до проверки офисом можно переснять. */
export function ReportPage() {
  const { t } = useTranslation()
  const camera = useRef<HTMLInputElement>(null)
  const gallery = useRef<HTMLInputElement>(null)
  const send = useSendReport()
  const types = useDriverReportTypes()
  const [tab, setTab] = useState<'send' | 'archive'>('send')
  const reports = useDriverReports(tab === 'archive')
  const current = useDriverTrips('current')
  const upcoming = useDriverTrips('upcoming')
  const [docType, setDocType] = useState('')
  const [tripId, setTripId] = useState('')
  const [error, setError] = useState<string>()
  const options = types.data?.results ?? []
  const effectiveType = options.some((o) => o.code === docType) ? docType : (options.find((o) => o.handler === 'sheet') ?? options[0])?.code ?? ''
  const handler = options.find((o) => o.code === effectiveType)?.handler
  const trips = [...(current.data?.results ?? []), ...(upcoming.data?.results ?? [])]
  const effectiveTrip = tripId !== '' ? tripId : trips[0] ? String(trips[0].id) : ''
  const onFile = async (file: File | undefined) => {
    if (!file || effectiveType === '') return
    setError(undefined)
    try {
      const { blob, name } = await shrinkImage(file)
      await send.mutateAsync({ file: blob, name, docType: effectiveType, trip: effectiveTrip !== '' ? Number(effectiveTrip) : null })
    } catch (e) {
      setError(e instanceof Error && e.message === 'image_too_large' ? t('ocr.tooLarge') : errorMessage(e, t))
    } finally {
      if (camera.current) camera.current.value = ''
      if (gallery.current) gallery.current.value = ''
    }
  }
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t('driver.tabs.report')}</h1>
      <Tabs variant="pills" label={t('driver.tabs.report')} active={tab} onChange={(k) => { setTab(k === 'archive' ? 'archive' : 'send') }} tabs={[{ key: 'send', label: t('driver.report.tabSend') }, { key: 'archive', label: t('driver.report.tabArchive') }]} />
      {tab === 'send' ? (
        <Card className="space-y-3 p-3">
          <Select label={t('ocr.docType')} value={effectiveType} options={options.map((o) => ({ value: o.code, label: o.name }))} onChange={setDocType} />
          <Select label={t('driver.report.trip')} value={effectiveTrip} placeholder={t('driver.report.noTrip')} options={trips.map((x) => ({ value: String(x.id), label: `${x.number} · ${x.from_city || '-'} → ${x.to_city || '-'}` }))} onChange={setTripId} />
          <input ref={camera} type="file" accept="image/*" capture="environment" className="sr-only" data-testid="report-camera" aria-label={t('driver.report.take')} onChange={(e) => { void onFile(e.target.files?.[0]) }} />
          <input ref={gallery} type="file" accept="image/jpeg,image/png,image/*" className="sr-only" data-testid="report-file" aria-label={t('driver.report.pick')} onChange={(e) => { void onFile(e.target.files?.[0]) }} />
          <Button variant="primary" icon={Camera} className="h-14! w-full text-base!" disabled={send.isPending || effectiveType === ''} onClick={() => { camera.current?.click() }}>
            {send.isPending ? t('driver.report.reading') : t('driver.report.take')}
          </Button>
          <Button icon={Paperclip} className="h-12! w-full" disabled={send.isPending || effectiveType === ''} onClick={() => { gallery.current?.click() }}>{t('driver.report.pick')}</Button>
          <p className="text-xs text-muted">{handler === 'sheet' ? t('driver.report.sheetHint') : t('driver.report.hint')}</p>
          {error ? <Banner kind="error">{error}</Banner> : null}
        </Card>
      ) : <p className="text-xs text-muted">{t('driver.report.archiveHint', { days: 180 })}</p>}
      {reports.isPending ? <Spinner /> : null}
      {reports.isError ? <Banner kind="error">{errorMessage(reports.error, t)}</Banner> : null}
      {reports.data?.results.length === 0 ? <EmptyState icon={Camera} title={tab === 'archive' ? t('driver.report.archiveEmpty') : t('driver.report.empty')} hint={tab === 'archive' ? undefined : t('driver.report.emptyHint')} /> : null}
      {reports.data?.results.map((d) => <ReportCard key={d.id} doc={d} archived={tab === 'archive'} />)}
    </div>
  )
}
