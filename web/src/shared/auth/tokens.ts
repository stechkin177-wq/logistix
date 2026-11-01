/**
 * Хранение токенов.
 *
 * access - ТОЛЬКО в памяти модуля (XSS не вынесет его из вкладки при перезагрузке,
 * на диск он не попадает). refresh - в sessionStorage: переживает перезагрузку страницы,
 * исчезает при закрытии вкладки. Компромисс: скрипт на странице (XSS) может прочитать refresh;
 * защита - строгие правила (нет dangerouslySetInnerHTML, валидация брендинга). На этапе 5 refresh
 * планируется перенести в httpOnly-cookie (тогда JS его не увидит).
 * Токены не логируются и не попадают в URL.
 */
const REFRESH_KEY = 'logistix.refresh'

let access: string | null = null

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function getAccess(): string | null {
  return access
}

export function getRefresh(): string | null {
  return storage()?.getItem(REFRESH_KEY) ?? null
}

export function setTokens(tokens: { access: string; refresh?: string }): void {
  access = tokens.access
  if (tokens.refresh) storage()?.setItem(REFRESH_KEY, tokens.refresh)
}

export function clearTokens(): void {
  access = null
  storage()?.removeItem(REFRESH_KEY)
}

export function hasTokens(): boolean {
  return access !== null || getRefresh() !== null
}
