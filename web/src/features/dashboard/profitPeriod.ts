import { useSyncExternalStore } from 'react'

/** Период прибыли на дашборде: пресеты и произвольный диапазон; выбор хранится в браузере. */
export type ProfitPreset = 'month' | 'prev_month' | 'quarter' | 'year' | 'custom'

export interface ProfitPeriod {
  preset: ProfitPreset
  /** Для custom: YYYY-MM-DD. */
  from?: string
  to?: string
}

export const DEFAULT_PERIOD: ProfitPeriod = { preset: 'month' }
const STORAGE_KEY = 'logistix.dashboard.profitPeriod'
const PRESETS: readonly string[] = ['month', 'prev_month', 'quarter', 'year', 'custom']
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export function readPeriod(): ProfitPeriod {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null') as Partial<ProfitPeriod> | null
    if (!raw || typeof raw.preset !== 'string' || !PRESETS.includes(raw.preset)) return DEFAULT_PERIOD
    if (raw.preset === 'custom') {
      return typeof raw.from === 'string' && typeof raw.to === 'string' && DATE_RE.test(raw.from) && DATE_RE.test(raw.to) && raw.from <= raw.to
        ? { preset: 'custom', from: raw.from, to: raw.to }
        : DEFAULT_PERIOD
    }
    return { preset: raw.preset }
  } catch {
    return DEFAULT_PERIOD
  }
}

export function savePeriod(period: ProfitPeriod): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(period))
  } catch {
    // хранилище недоступно - выбор действует до перезагрузки
  }
}

const iso = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d)).toISOString().slice(0, 10)

/** Сегодняшняя дата в часовом поясе компании: [год, месяц 0-11, день]. */
function todayIn(timeZone: string, now = new Date()): [number, number, number] {
  let text: string
  try {
    text = new Intl.DateTimeFormat('en-CA', { timeZone }).format(now)
  } catch {
    text = now.toISOString().slice(0, 10)
  }
  const [y = 1970, m = 1, d = 1] = text.split('-').map(Number)
  return [y, m - 1, d]
}

/** Параметры запроса для периода; null - текущий месяц (сервер считает его сам, в поясе компании). */
export function periodQuery(period: ProfitPeriod, timeZone: string, now = new Date()): { profit_from: string; profit_to: string } | null {
  const [y, m] = todayIn(timeZone, now)
  switch (period.preset) {
    case 'month':
      return null
    case 'prev_month':
      return { profit_from: iso(y, m - 1, 1), profit_to: iso(y, m, 0) }
    case 'quarter': {
      const q = Math.floor(m / 3) * 3
      return { profit_from: iso(y, q, 1), profit_to: iso(y, q + 3, 0) }
    }
    case 'year':
      return { profit_from: iso(y, 0, 1), profit_to: iso(y, 12, 0) }
    case 'custom':
      return period.from && period.to ? { profit_from: period.from, profit_to: period.to } : null
  }
}

// --- общее хранилище периода: дашборд и финансы показывают один и тот же период ---
const EVENT = 'logistix:period'
let cachedRaw: string | null | undefined
let cached: ProfitPeriod = DEFAULT_PERIOD

function snapshot(): ProfitPeriod {
  let raw: string | null = null
  try { raw = window.localStorage.getItem(STORAGE_KEY) } catch { /* хранилище недоступно */ }
  if (raw !== cachedRaw) { cachedRaw = raw; cached = readPeriod() }
  return cached
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(EVENT, listener)
  window.addEventListener('storage', listener)
  return () => { window.removeEventListener(EVENT, listener); window.removeEventListener('storage', listener) }
}

/** Выбранный период и его установка (запоминается в браузере, меняется сразу во всех разделах). */
export function usePeriod(): [ProfitPeriod, (next: ProfitPeriod) => void] {
  const period = useSyncExternalStore(subscribe, snapshot, () => DEFAULT_PERIOD)
  const set = (next: ProfitPeriod) => { savePeriod(next); window.dispatchEvent(new Event(EVENT)) }
  return [period, set]
}

/** Параметры финансовой сводки (date_from/date_to); null - текущий месяц. */
export function financePeriodQuery(period: ProfitPeriod, timeZone: string): { date_from: string; date_to: string } | null {
  const q = periodQuery(period, timeZone)
  return q ? { date_from: q.profit_from, date_to: q.profit_to } : null
}
