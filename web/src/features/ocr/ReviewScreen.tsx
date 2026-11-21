import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { WriteButton } from '../../shared/ui/WriteButton'
import { Check } from '../../shared/ui/icons'
import { getOcrImage } from './api'
import { RemoteImage } from './ImageViewer'
import { useSaveOcrReview } from './hooks'
import { flattenSheet, sumOf } from './sheet'
import type { OcrDocument, ReviewData } from './types'

/** Сверка с фото: слева снимок (увеличение, поворот), справа прочитанные значения. Сначала то, что
 * нейросеть пометила сомнительным: «✓» подтверждает значение, любую ячейку можно поправить. Правки
 * и подтверждения сохраняются в документе; «Готово» отмечает документ проверенным. */
export function ReviewScreen({ doc, onClose }: { doc: OcrDocument; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveOcrReview()
  const flags = doc.sheet.flags ?? {}
  const alt = doc.sheet.alt ?? {}
  const rows = useMemo(() => flattenSheet(doc.sheet.raw ?? {}), [doc.sheet.raw])
  const [edits, setEdits] = useState<Record<string, string>>(doc.review.edits ?? {})
  const [checked, setChecked] = useState<Set<string>>(new Set(doc.review.checked ?? []))
  const value = (path: string, original: string) => edits[path] ?? original
  const flaggedRows = rows.filter((r) => flags[r.path] && !checked.has(r.path) && edits[r.path] === undefined)
  const doubtful = rows.filter((r) => flags[r.path])
  const persist = (done: boolean) => {
    const review: ReviewData = { edits, checked: [...checked] }
    save.mutate({ id: doc.id, review, done }, { onSuccess: () => { if (done) onClose() } })
  }
  const setEdit = (path: string, original: string, next: string) => {
    const rest = Object.fromEntries(Object.entries(edits).filter(([k]) => k !== path))
    setEdits(next === original ? rest : { ...rest, [path]: next })
  }
  const toggle = (path: string) => {
    const next = new Set(checked)
    if (next.has(path)) next.delete(path)
    else next.add(path)
    setChecked(next)
  }
  const renderRow = (r: (typeof rows)[number]) => {
    const reasons = flags[r.path]
    const current = value(r.path, r.value)
    const sum = sumOf(current)
    const done = checked.has(r.path)
    return (
      <div key={r.path} className={`grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 border-t border-line py-1.5 ${reasons && !done ? 'bg-amber-50 dark:bg-amber-950/40' : ''}`} data-testid="review-row" data-flagged={reasons && !done ? 'true' : undefined}>
        <div className="min-w-0">
          <p className="truncate text-xs text-muted">{r.label}</p>
          {reasons ? <p className="text-xs text-amber-900 dark:text-amber-200">{reasons.join('; ')}</p> : null}
          {alt[r.path] ? <p className="text-xs text-amber-800 dark:text-amber-200">{t('ocr.sheet.alt', { value: alt[r.path] })}</p> : null}
        </div>
        <div>
          <input
            aria-label={r.label}
            className="h-8 w-full rounded-control border border-line bg-surface px-2 text-sm"
            value={current}
            maxLength={200}
            onChange={(e) => { setEdit(r.path, r.value, e.target.value) }}
          />
          {sum !== null ? <p className="mt-0.5 text-xs text-muted">{sum}</p> : null}
        </div>
        {reasons ? (
          <Button aria-pressed={done} aria-label={t('ocr.review_.confirm')} title={t('ocr.review_.confirm')} variant={done ? 'primary' : 'secondary'} icon={Check} onClick={() => { toggle(r.path) }} />
        ) : <span className="w-9" />}
      </div>
    )
  }
  const sections = [...new Set(rows.map((r) => r.section))]
  return (
    <Dialog
      open
      title={t('ocr.review_.title', { name: doc.doc_type_name })}
      onClose={onClose}
      busy={save.isPending}
      width="max-w-6xl"
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission="ocr.update" disabled={save.isPending} onClick={() => { persist(false) }}>{t('ocr.review_.saveDraft')}</WriteButton>
          <WriteButton permission="ocr.update" variant="primary" disabled={save.isPending || flaggedRows.length > 0} title={flaggedRows.length > 0 ? t('ocr.review_.needConfirm') : undefined} onClick={() => { persist(true) }}>
            {t('ocr.review_.done')}
          </WriteButton>
        </>
      }
    >
      <div className="grid h-[70vh] gap-3 md:grid-cols-2">
        <div className="flex min-h-0 flex-col">
          {doc.has_file ? <RemoteImage queryKey={['ocr', 'image', doc.id]} load={() => getOcrImage(doc.id)} name={doc.original_name} className="flex-1" /> : <Banner kind="warning">{t('ocr.review_.noPhoto')}</Banner>}
        </div>
        <div className="thin-scroll min-h-0 overflow-y-auto pr-1">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted">
            <Badge tone={flaggedRows.length > 0 ? 'warning' : 'success'}>{t('ocr.review_.left', { left: flaggedRows.length, total: doubtful.length })}</Badge>
            <span>{t('ocr.review_.hint')}</span>
          </div>
          {(doc.sheet.notes ?? []).map((n) => <p key={n} className="mb-1 rounded-control bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">{n}</p>)}
          {flaggedRows.length > 0 ? (
            <section aria-label={t('ocr.review_.doubts')}>
              <h3 className="text-sm font-semibold">{t('ocr.review_.doubts')}</h3>
              {flaggedRows.map((r) => renderRow(r))}
            </section>
          ) : null}
          {sections.map((section) => (
            <section key={section} className="mt-3">
              <h3 className="text-sm font-semibold">{t(`ocr.sheet.sections.${section}`, section)}</h3>
              {rows.filter((r) => r.section === section && !flaggedRows.includes(r)).map((r) => renderRow(r))}
            </section>
          ))}
          {rows.length === 0 ? <p className="text-sm text-muted">{t('ocr.sheet.empty')}</p> : null}
          {save.isError ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
        </div>
      </div>
    </Dialog>
  )
}
