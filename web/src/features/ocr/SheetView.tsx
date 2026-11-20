import { useTranslation } from 'react-i18next'
import type { SheetPage } from './types'

interface Row { path: string; label: string; value: string }

/** Плоский список прочитанных значений раздела: путь («fuel_tractor[1].liters») -> значение. */
function flatten(node: unknown, path: string, out: Row[], base: string) {
  if (node === null || node === undefined || node === '') return
  if (Array.isArray(node)) {
    node.forEach((v, i) => { flatten(v, `${path}[${String(i)}]`, out, base) })
  } else if (typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) flatten(v, path ? `${path}.${k}` : k, out, base)
  } else if (typeof node === 'string' || typeof node === 'number' || typeof node === 'boolean') {
    out.push({ path, label: path.slice(base.length).replace(/^\./, '') || path, value: String(node) })
  }
}

/** Результат чтения рукописного листа: значения по разделам, сомнительные подсвечены с причиной. */
export function SheetView({ sheet }: { sheet: Partial<SheetPage> }) {
  const { t } = useTranslation()
  const raw = sheet.raw ?? {}
  const flags = sheet.flags ?? {}
  const alt = sheet.alt ?? {}
  const sections = Object.entries(raw).filter(([k]) => k !== 'page_type').map(([key, value]) => {
    const rows: Row[] = []
    flatten(value, key, rows, key)
    return { key, rows }
  }).filter((s) => s.rows.length > 0)
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
