const FALLBACK = [
  'Asia/Almaty', 'Asia/Aqtau', 'Asia/Aqtobe', 'Asia/Oral', 'Asia/Qyzylorda', 'Asia/Tashkent', 'Asia/Bishkek',
  'Europe/Moscow', 'Europe/Minsk', 'Europe/Kyiv', 'Europe/Istanbul', 'Europe/Berlin', 'Europe/London',
  'Asia/Dubai', 'Asia/Shanghai', 'UTC',
]

/** Часовые пояса IANA: из Intl, если браузер умеет, иначе короткий список. */
export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  try {
    const list = intl.supportedValuesOf?.('timeZone')
    if (list && list.length > 0) return list.includes('UTC') ? list : [...list, 'UTC']
  } catch {
    // старый движок: используем запасной список
  }
  return FALLBACK
}
