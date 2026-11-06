/** Цель возврата после входа: только внутренний путь вида /abc (не //host, не схема, не \). */
export function safeRedirect(raw: string | null | undefined): string {
  if (!raw) return '/'
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return '/'
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(raw)) return '/'
  if (raw.startsWith('/login')) return '/'
  return raw
}

export function loginPath(target: string): string {
  const safe = safeRedirect(target)
  return safe === '/' ? '/login' : `/login?next=${encodeURIComponent(safe)}`
}
