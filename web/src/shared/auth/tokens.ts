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
/**
 * Эпоха сессии: растёт при выходе (clearTokens) и при каждой явной установке токенов (вход,
 * смена компании). Запись результата refresh (applyRefreshed) эпоху НЕ меняет, но сверяется с ней:
 * запоздавший ответ refresh не может перезаписать выход или другую компанию.
 */
let epoch = 0

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

export function getEpoch(): number {
  return epoch
}

/** Явная установка токенов (вход, смена компании): начинает новую эпоху. */
export function setTokens(tokens: { access: string; refresh?: string }): void {
  epoch++
  access = tokens.access
  if (tokens.refresh) storage()?.setItem(REFRESH_KEY, tokens.refresh)
}

/** Запись результата refresh; false - сессия изменилась за время запроса, результат отброшен. */
export function applyRefreshed(tokens: { access: string; refresh?: string }, startEpoch: number): boolean {
  if (startEpoch !== epoch) return false
  access = tokens.access
  if (tokens.refresh) storage()?.setItem(REFRESH_KEY, tokens.refresh)
  return true
}

export function clearTokens(): void {
  epoch++
  access = null
  storage()?.removeItem(REFRESH_KEY)
}

export function hasTokens(): boolean {
  return access !== null || getRefresh() !== null
}
