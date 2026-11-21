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
import { Camera, Trash2 } from '../../shared/ui/icons'
import { shrinkImage } from '../ocr/image'
import { SheetView } from '../ocr/SheetView'
import type { OcrDocType, OcrDocument } from '../ocr/types'
import { useDeleteReport, useDriverReports, useDriverTrips, useSendReport } from './hooks'

const TYPES: OcrDocType[] = ['report_sheet', 'fuel_receipt', 'waybill', 'cmr', 'other']
const FIELD_ORDER = ['date', 'amount', 'liters', 'price_per_liter', 'fuel_type', 'plate'] as const

function ReportCard({ doc }: { doc: OcrDocument }) {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const remove = useDeleteReport()
  const [open, setOpen] = useState(false)
  const reviewed = doc.reviewed_at !== null
  const flagged = doc.doc_type === 'report_sheet' ? Object.keys(doc.sheet.flags ?? {}).length : 0
  return (
    <Card className="space-y-2 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{t(`ocr.types.${doc.doc_type}`)}</p>
          <p className="text-xs text-muted">{dateTime(doc.created_at)}{doc.trip_number ? ` · ${doc.trip_number}` : ''}</p>
        </div>
        <Badge tone={reviewed ? 'success' : doc.status === 'failed' ? 'danger' : 'info'}>
          {reviewed ? t('driver.report.reviewed') : doc.status === 'failed' ? t('ocr.statuses.failed') : t('driver.report.sent')}
        </Badge>
      </div>
      {doc.status === 'failed' ? <Banner kind="error">{doc.error}</Banner> : null}
      {flagged > 0 ? <Banner kind="warning">{t('driver.report.doubts', { count: flagged })}</Banner> : null}
      {doc.doc_type !== 'report_sheet' && doc.status === 'done' ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          {FIELD_ORDER.filter((k) => doc.fields[k]).map((k) => (
            <div key={k} className="contents"><dt className="text-muted">{t(`ocr.fields.${k}`)}</dt><dd className="text-right font-medium">{k === 'fuel_type' ? t(`ocr.fuel.${doc.fields[k] ?? 'diesel'}`) : doc.fields[k]}</dd></div>
          ))}
        </dl>
      ) : null}
      {doc.doc_type === 'report_sheet' && doc.status === 'done' ? (
        <>
          <Button onClick={() => { setOpen(!open) }}>{open ? t('driver.report.hide') : t('driver.report.show')}</Button>
          {open ? <SheetView sheet={doc.sheet} /> : null}
        </>
      ) : null}
      {!reviewed ? (
        <Button variant="dangerSoft" icon={Trash2} disabled={remove.isPending} onClick={() => { remove.mutate(doc.id) }}>{t('driver.report.retake')}</Button>
      ) : null}
      {remove.isError ? <Banner kind="error">{errorMessage(remove.error, t)}</Banner> : null}
    </Card>
  )
}

/** Вкладка «Отчёт»: фото рукописного листа, чека или документа; распознаётся сразу, сомнительные
 * значения подсвечены; отправка в офис происходит самой загрузкой, до проверки офисом можно переснять. */
export function ReportPage() {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const send = useSendReport()
  const reports = useDriverReports()
  const current = useDriverTrips('current')
  const upcoming = useDriverTrips('upcoming')
  const [docType, setDocType] = useState<OcrDocType>('report_sheet')
  const [tripId, setTripId] = useState('')
  const [error, setError] = useState<string>()
  const trips = [...(current.data?.results ?? []), ...(upcoming.data?.results ?? [])]
  const effectiveTrip = tripId !== '' ? tripId : trips[0] ? String(trips[0].id) : ''
  const onFile = async (file: File | undefined) => {
    if (!file) return
    setError(undefined)
    try {
      const { blob, name } = await shrinkImage(file)
      await send.mutateAsync({ file: blob, name, docType, trip: effectiveTrip !== '' ? Number(effectiveTrip) : null })
    } catch (e) {
      setError(e instanceof Error && e.message === 'image_too_large' ? t('ocr.tooLarge') : errorMessage(e, t))
    } finally {
      if (input.current) input.current.value = ''
    }
  }
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{t('driver.tabs.report')}</h1>
      <Card className="space-y-3 p-3">
        <Select label={t('ocr.docType')} value={docType} options={TYPES.map((v) => ({ value: v, label: t(`ocr.types.${v}`) }))} onChange={(v) => { setDocType(TYPES.find((x) => x === v) ?? 'other') }} />
        <Select label={t('driver.report.trip')} value={effectiveTrip} placeholder={t('driver.report.noTrip')} options={trips.map((x) => ({ value: String(x.id), label: `${x.number} · ${x.from_city || '-'} → ${x.to_city || '-'}` }))} onChange={setTripId} />
        <input ref={input} type="file" accept="image/jpeg,image/png,image/*" capture="environment" className="sr-only" data-testid="report-file" aria-label={t('driver.report.take')} onChange={(e) => { void onFile(e.target.files?.[0]) }} />
        <Button variant="primary" icon={Camera} className="h-14! w-full text-base!" disabled={send.isPending} onClick={() => { input.current?.click() }}>
          {send.isPending ? t('driver.report.reading') : t('driver.report.take')}
        </Button>
        <p className="text-xs text-muted">{docType === 'report_sheet' ? t('driver.report.sheetHint') : t('driver.report.hint')}</p>
        {error ? <Banner kind="error">{error}</Banner> : null}
      </Card>
      {reports.isPending ? <Spinner /> : null}
      {reports.isError ? <Banner kind="error">{errorMessage(reports.error, t)}</Banner> : null}
      {reports.data?.results.length === 0 ? <EmptyState icon={Camera} title={t('driver.report.empty')} hint={t('driver.report.emptyHint')} /> : null}
      {reports.data?.results.map((d) => <ReportCard key={d.id} doc={d} />)}
    </div>
  )
}
