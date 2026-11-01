import { describe, expect, it } from 'vitest'
import { formatDate, formatDateTime, fromInputDateTime, toInputDateTime } from './datetime'

describe('datetime', () => {
  it('показывает момент в поясе компании, а не в поясе браузера', () => {
    expect(formatDateTime('2026-10-31T20:30:00Z', 'Asia/Almaty')).toBe('01.11.2026, 01:30')
    expect(formatDateTime('2026-10-31T20:30:00Z', 'UTC')).toBe('31.10.2026, 20:30')
  })
  it('пустое и невалидное - тире, неизвестный пояс не роняет', () => {
    expect(formatDateTime(null, 'Asia/Almaty')).toBe('—')
    expect(formatDateTime('мусор', 'Asia/Almaty')).toBe('—')
    expect(formatDateTime('2026-10-31T20:30:00Z', 'Mars/Base')).toBe('01.11.2026, 01:30')
  })
  it('чистая дата не сдвигается', () => {
    expect(formatDate('2026-10-31', 'Pacific/Honolulu')).toBe('31.10.2026')
  })
  it('круговое преобразование datetime-local <-> ISO в поясе компании', () => {
    const iso = fromInputDateTime('2026-11-01T09:00', 'Asia/Almaty')
    expect(iso).toBe('2026-11-01T04:00:00.000Z')
    expect(toInputDateTime(iso, 'Asia/Almaty')).toBe('2026-11-01T09:00')
    expect(fromInputDateTime('', 'Asia/Almaty')).toBeNull()
  })
})
