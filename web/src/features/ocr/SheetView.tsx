import { useTranslation } from 'react-i18next'
import { flattenSheet, sumOf } from './sheet'
import type { SheetPage } from './types'

/** Результат чтения рукописного листа: значения по разделам, сомнительные подсвечены с причиной. */
export function SheetView({ sheet }: { sheet: Partial<SheetPage> }) {
  const { t } = useTranslation()
  const raw = sheet.raw ?? {}
  const flags = sheet.flags ?? {}
  const alt = sheet.alt ?? {}
  const all = flattenSheet(raw)
  const sections = [...new Set(all.map((r) => r.section))].map((key) => ({ key, rows: all.filter((r) => r.section === key) }))
  const flagged = Object.keys(flags).length
  return (
    <div className="space-y-3" data-testid="sheet-view">
      <p className="text-xs text-muted">
        {t('ocr.sheet.summary', { pageType: t(`ocr.sheet.pageTypes.${sheet.page_type ?? 'other'}`, sheet.page_type ?? ''), flagged })}
        {sheet.models?.length ? ` ${t('ocr.sheet.models', { models: sheet.models.join(', ') })}` : ''}
      </p>
      {(sheet.notes ?? []).map((n) => <p key={n} className="rounded-control bg-amber-50 px-2 py-1.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">{n}</p>)}
      {sections.map(({ key, rows }) => (
        <div key={key}>
          <h3 className="mb-1 text-sm font-semibold">{t(`ocr.sheet.sections.${key}`, key)}</h3>
          <table className="w-full text-sm">
            <tbody>
              {rows.map((r) => {
                const reasons = flags[r.path]
                const other = alt[r.path]
                return (
                  <tr key={r.path} className={`border-t border-line ${reasons ? 'bg-amber-50 dark:bg-amber-950/40' : ''}`} data-flagged={reasons ? 'true' : undefined}>
                    <td className="py-1 pr-2 text-muted">{r.label}</td>
                    <td className="py-1 pr-2 font-medium">
                      {r.value}
                      {sumOf(r.value) ? <span className="ml-2 text-xs font-normal text-muted">{sumOf(r.value)}</span> : null}
                      {other ? <span className="ml-2 text-xs text-amber-800 dark:text-amber-200">({t('ocr.sheet.alt', { value: other })})</span> : null}
                    </td>
                    <td className="py-1 text-xs text-amber-900 dark:text-amber-200">{reasons?.join('; ')}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
      {sections.length === 0 ? <p className="text-sm text-muted">{t('ocr.sheet.empty')}</p> : null}
    </div>
  )
}
