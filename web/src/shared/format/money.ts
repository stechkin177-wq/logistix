const NBSP = ' '
const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/

export interface MoneyFormat {
  currency?: string
  /** Разделитель дроби; по умолчанию запятая (ru/kk). */
  decimalSeparator?: string
  /** Минимум знаков после разделителя (по умолчанию 2). */
  minFraction?: number
}

/**
 * Форматирует денежную СТРОКУ API ("1234567.89") без перевода в число: разряды группируются по тройкам
 * неразрывным пробелом, цифры не теряются. Не число (NaN, Infinity, пусто, null) даёт "—".
 */
export function formatMoney(value: string | null | undefined, opts: MoneyFormat = {}): string {
  const match = typeof value === 'string' ? DECIMAL.exec(value.trim()) : null
  if (!match) return '—'
  const [, sign = '', integer = '0', fraction = ''] = match
  const grouped = integer.replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
  const minFraction = opts.minFraction ?? 2
  const digits = fraction.padEnd(minFraction, '0')
  const body = `${sign}${grouped}${digits ? `${opts.decimalSeparator ?? ','}${digits}` : ''}`
  return opts.currency ? `${body}${NBSP}${opts.currency}` : body
}
