/**
 * Имя файла из заголовка сервера не доверяется: остаётся безопасное базовое имя
 * (без путей, "..", управляющих символов, кавычек), не длиннее 100 символов.
 */
export function safeFilename(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback
  // eslint-disable-next-line no-control-regex
  const cleaned = raw.replace(/[\u0000-\u001f\u007f"'<>:*?|]/g, '')
  const base = cleaned.split(/[/\\]/).pop() ?? ''
  const name = base.replace(/\.{2,}/g, '.').replace(/^[.\s]+/, '').trim().slice(-100)
  return name === '' ? fallback : name
}
