export interface SheetRow { path: string; section: string; label: string; value: string }

/** Плоский список прочитанных значений листа: путь («fuel_tractor[1].liters») -> значение. */
export function flattenSheet(raw: Record<string, unknown>): SheetRow[] {
  const out: SheetRow[] = []
  const walk = (node: unknown, path: string, section: string) => {
    if (node === null || node === undefined || node === '') return
    if (Array.isArray(node)) {
      node.forEach((v, i) => { walk(v, `${path}[${String(i)}]`, section) })
    } else if (typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) walk(v, path ? `${path}.${k}` : k, section)
    } else if (typeof node === 'string' || typeof node === 'number' || typeof node === 'boolean') {
      out.push({ path, section, label: path.slice(section.length).replace(/^\./, '') || path, value: String(node) })
    }
  }
  for (const [key, value] of Object.entries(raw)) {
    if (key !== 'page_type') walk(value, key, key)
  }
  return out
}

/** «2000+200» -> «2000 + 200 = 2200»; обычное число или текст -> null (расшифровка не нужна). */
export function sumOf(text: string): string | null {
  const parts = text.replace(/\s+/g, '').replace(/,/g, '.').split('+')
  if (parts.length < 2 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null
  const total = parts.reduce((acc, p) => acc + Number(p), 0)
  return `${parts.join(' + ')} = ${String(Math.round(total * 100) / 100)}`
}
