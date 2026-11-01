import { describe, expect, it } from 'vitest'
import { computeTotals, toCents, vatPercent } from './invoiceMath'

describe('invoiceMath', () => {
  it('toCents разбирает суммы без потери копеек и отвергает мусор', () => {
    expect(toCents('1000')).toBe(100000n)
    expect(toCents('0.33')).toBe(33n)
    expect(toCents('12.5')).toBe(1250n)
    expect(toCents('')).toBeNull()
    expect(toCents('1,5')).toBeNull()
    expect(toCents('1.234')).toBeNull()
    expect(toCents('-1')).toBeNull()
  })

  it('vatPercent: none = 0, число, иначе null', () => {
    expect(vatPercent('none')).toBe(0)
    expect(vatPercent('16')).toBe(16)
    expect(vatPercent('12.5')).toBe(12.5)
    expect(vatPercent('abc')).toBeNull()
    expect(vatPercent('101')).toBeNull()
  })

  it('НДС считается от суммы, округление вверх с половины, как на сервере', () => {
    expect(computeTotals(['0.33', '0.33', '0.33'], 16)).toEqual({ net: '0.99', vat: '0.16', gross: '1.15' })
    expect(computeTotals(['1000'], 16)).toEqual({ net: '1000.00', vat: '160.00', gross: '1160.00' })
    expect(computeTotals(['0.05'], 10)).toEqual({ net: '0.05', vat: '0.01', gross: '0.06' }) // 0.005 -> 0.01
    expect(computeTotals([], 16)).toEqual({ net: '0.00', vat: '0.00', gross: '0.00' })
    expect(computeTotals(['100'], 0)).toEqual({ net: '100.00', vat: '0.00', gross: '100.00' })
  })
})
