import { describe, expect, it } from 'vitest'
import { formatMoney } from './money'

describe('formatMoney', () => {
  it('группирует разряды строки без перевода в число', () => {
    expect(formatMoney('1234567.89')).toBe('1 234 567,89')
    expect(formatMoney('1234567.89', { decimalSeparator: '.' })).toBe('1 234 567.89')
  })
  it('не теряет точность на больших суммах', () => {
    expect(formatMoney('12345678901234567890.12')).toBe('12 345 678 901 234 567 890,12')
  })
  it('дополняет и сохраняет дробную часть, поддерживает минус', () => {
    expect(formatMoney('5')).toBe('5,00')
    expect(formatMoney('-1000.5')).toBe('-1 000,50')
    expect(formatMoney('0.00')).toBe('0,00')
  })
  it('добавляет код валюты', () => {
    expect(formatMoney('100.00', { currency: 'KZT' })).toBe('100,00 KZT')
  })
  it('мусор и null показывает как тире', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('NaN')).toBe('—')
    expect(formatMoney('Infinity')).toBe('—')
    expect(formatMoney('')).toBe('—')
  })
})
