/** Арифметика сумм счёта на клиенте (в копейках, BigInt): зеркало backend/apps/finance/money.py. */

const AMOUNT_RE = /^\d{1,12}(\.\d{1,2})?$/

/** Сумма "1234.5" -> копейки; пусто/мусор/отрицательное -> null. */
export function toCents(value: string): bigint | null {
  const text = value.trim()
  if (!AMOUNT_RE.test(text)) return null
  const [whole = '0', frac = ''] = text.split('.')
  return BigInt(whole) * 100n + BigInt(frac.padEnd(2, '0'))
}

export function fromCents(cents: bigint): string {
  const sign = cents < 0n ? '-' : ''
  const abs = cents < 0n ? -cents : cents
  return `${sign}${String(abs / 100n)}.${String(abs % 100n).padStart(2, '0')}`
}

/** Процент из code значения справочника «Ставки НДС»: none = 0, число 0..100, иначе null. */
export function vatPercent(code: string): number | null {
  if (code === 'none') return 0
  if (!/^\d{1,3}(\.\d{1,4})?$/.test(code)) return null
  const value = Number(code)
  return value >= 0 && value <= 100 ? value : null
}

export interface Totals {
  net: string
  vat: string
  gross: string
}

/** НДС от общей суммы (не по позициям), округление вверх с половины; нечисловые суммы пропускаются. */
export function computeTotals(amounts: string[], percent: number): Totals {
  const net = amounts.reduce((sum, a) => sum + (toCents(a) ?? 0n), 0n)
  const basisPoints = BigInt(Math.round(percent * 100))
  const vat = (net * basisPoints + 5000n) / 10000n
  return { net: fromCents(net), vat: fromCents(vat), gross: fromCents(net + vat) }
}
