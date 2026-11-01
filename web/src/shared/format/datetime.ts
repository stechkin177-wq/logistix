/** Единственное место форматирования дат: все даты показываются в часовом поясе компании (session.company.timezone). */

const FALLBACK_TZ = 'Asia/Almaty'

function safeZone(tz: string | undefined): string {
  if (!tz) return FALLBACK_TZ
  try {
    new Intl.DateTimeFormat('ru-RU', { timeZone: tz })
    return tz
  } catch {
    return FALLBACK_TZ
  }
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** "31.10.2026, 14:30" в поясе компании; невалидное или пустое - "—". */
export function formatDateTime(value: string | Date | null | undefined, tz: string | undefined, lang = 'ru'): string {
  const date = toDate(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat(lang === 'kk' ? 'kk-KZ' : 'ru-RU', {
    timeZone: safeZone(tz),
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date)
}

/** Только дата. Чистая дата без времени ("2026-10-31", поле date строки заказа) не сдвигается поясом. */
export function formatDate(value: string | Date | null | undefined, tz: string | undefined, lang = 'ru'): string {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y = '', m = '', d = ''] = value.split('-')
    return `${d}.${m}.${y}`
  }
  const date = toDate(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat(lang === 'kk' ? 'kk-KZ' : 'ru-RU', {
    timeZone: safeZone(tz),
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
}

function zoneParts(date: Date, tz: string): Record<string, number> {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const out: Record<string, number> = {}
  for (const part of parts) if (part.type !== 'literal') out[part.type] = Number(part.value)
  return out
}

function offsetMs(date: Date, tz: string): number {
  const p = zoneParts(date, tz)
  const asUtc = Date.UTC(p.year ?? 0, (p.month ?? 1) - 1, p.day ?? 1, p.hour ?? 0, p.minute ?? 0, p.second ?? 0)
  return asUtc - Math.floor(date.getTime() / 1000) * 1000
}

const pad = (n: number) => String(n).padStart(2, '0')

/** ISO-момент -> значение для <input type="datetime-local"> ("2026-10-31T14:30") в поясе компании. */
export function toInputDateTime(iso: string | null | undefined, tz: string | undefined): string {
  const date = toDate(iso)
  if (!date) return ''
  const p = zoneParts(date, safeZone(tz))
  return `${String(p.year).padStart(4, '0')}-${pad(p.month ?? 1)}-${pad(p.day ?? 1)}T${pad(p.hour ?? 0)}:${pad(p.minute ?? 0)}`
}

/** Значение datetime-local, понимаемое как время в поясе компании -> ISO UTC. Пусто/мусор -> null. */
export function fromInputDateTime(local: string, tz: string | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local)
  if (!m) return null
  const [y, mo, d, h, mi] = m.slice(1).map(Number) as [number, number, number, number, number]
  const zone = safeZone(tz)
  const guess = Date.UTC(y, mo - 1, d, h, mi)
  if (Number.isNaN(guess)) return null
  let result = guess - offsetMs(new Date(guess), zone)
  result = guess - offsetMs(new Date(result), zone) // повтор у границ перехода на летнее время
  return new Date(result).toISOString()
}
