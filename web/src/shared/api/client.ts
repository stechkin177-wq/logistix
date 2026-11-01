import { applyRefreshed, clearTokens, getAccess, getEpoch, getRefresh } from '../auth/tokens'
import { ApiError, buildApiError } from './errors'
import { emitApiEvent } from './events'

/** Единственное место, где вызывается fetch. */
const BASE = '/api'

export type Query = Record<string, string | number | boolean | null | undefined>

interface RequestOptions {
  query?: Query
  body?: unknown
  form?: FormData
  /** false - без Authorization и без обновления токена (вход, refresh). */
  auth?: boolean
  /** Отмена запроса (TanStack Query передаёт сигнал при смене фильтров). */
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function send(method: string, path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = opts.auth === false ? null : getAccess()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) {
    body = opts.form // Content-Type с boundary выставит браузер
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  try {
    return await fetch(buildUrl(path, opts.query), { method, headers, body, signal: opts.signal })
  } catch (error) {
    if (opts.signal?.aborted) throw error // отмена - не сбой сети
    throw new ApiError(0, 'network_error', '')
  }
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined
  const text = await response.text()
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

/**
 * ok - токен обновлён; changed - за время запроса сессия изменилась (выход/смена компании), результат
 * отброшен; rejected - сервер отклонил refresh (сессия очищена); unavailable - сеть/5xx (токены целы).
 */
type RefreshResult =
  | { kind: 'ok' | 'changed' | 'rejected' }
  | { kind: 'unavailable'; error: ApiError }

let refreshing: Promise<RefreshResult> | null = null

async function doRefresh(): Promise<RefreshResult> {
  const refresh = getRefresh()
  if (!refresh) {
    return { kind: 'rejected' }
  }
  const startEpoch = getEpoch()
  let response: Response
  try {
    response = await send('POST', '/auth/refresh/', { body: { refresh }, auth: false })
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 0
    return { kind: 'unavailable', error: new ApiError(status, 'network_error', '') }
  }
  if (response.ok) {
    const data = (await readBody(response)) as { access?: unknown; refresh?: unknown } | undefined
    if (typeof data?.access !== 'string') {
      return { kind: 'unavailable', error: new ApiError(response.status, 'refresh_unavailable', '') }
    }
    const applied = applyRefreshed(
      { access: data.access, refresh: typeof data.refresh === 'string' ? data.refresh : undefined },
      startEpoch,
    )
    return { kind: applied ? 'ok' : 'changed' }
  }
  if ([400, 401, 403].includes(response.status)) {
    if (startEpoch !== getEpoch()) return { kind: 'changed' }
    sessionLost()
    return { kind: 'rejected' }
  }
  return { kind: 'unavailable', error: new ApiError(response.status, 'refresh_unavailable', '') }
}

/** Одно обновление на всех: параллельные 401 ждут один и тот же promise. */
function refreshAccess(): Promise<RefreshResult> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null
  })
  return refreshing
}

function sessionLost(): void {
  clearTokens()
  emitApiEvent('logout')
}

/** Запрос с авторизацией и одним обновлением токена; возвращает ответ (в т.ч. не-2xx, кроме 401). */
async function execute(method: string, path: string, opts: RequestOptions): Promise<Response> {
  const authed = opts.auth !== false
  const startEpoch = getEpoch()
  // чужой (позже начавшейся) сессии этот запрос не трогает: только своя эпоха может её завершить
  const loseSession = (): void => {
    if (getEpoch() === startEpoch) sessionLost()
  }
  if (authed && !getAccess() && getRefresh()) {
    const result = await refreshAccess()
    if (result.kind === 'unavailable') throw result.error
    if (result.kind === 'rejected') throw new ApiError(401, 'session_expired', '')
  }
  let response = await send(method, path, opts)
  if (response.status === 401 && authed) {
    if (!getRefresh()) {
      loseSession()
      throw buildApiError(401, await readBody(response))
    }
    const result = await refreshAccess()
    if (result.kind === 'unavailable') throw result.error
    if (result.kind === 'rejected') throw buildApiError(401, await readBody(response))
    response = await send(method, path, opts) // повтор ровно один раз (с актуальными токенами)
    if (response.status === 401) {
      loseSession()
      throw buildApiError(401, await readBody(response))
    }
  }
  return response
}

async function failWith(response: Response): Promise<never> {
  const error = buildApiError(response.status, await readBody(response))
  if (error.code === 'subscription_blocked') emitApiEvent('blocked')
  if (error.code === 'subscription_readonly') emitApiEvent('readonly')
  throw error
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const response = await execute(method, path, opts)
  if (!response.ok) return failWith(response)
  return (await readBody(response)) as T
}

function filenameFrom(response: Response): string | null {
  const header = response.headers.get('Content-Disposition') ?? ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      // падаем на обычное имя
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1] ?? null
}

export const api = {
  get: <T>(path: string, query?: Query, opts?: Pick<RequestOptions, 'auth' | 'signal'>) =>
    request<T>('GET', path, { ...opts, query }),
  post: <T>(path: string, body?: unknown, opts?: Pick<RequestOptions, 'auth'>) =>
    request<T>('POST', path, { ...opts, body }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
  /** Скачивание файла (Excel): тело как blob, имя из Content-Disposition. Ошибки - ApiError как у остальных. */
  download: async (path: string, query?: Query, opts?: Pick<RequestOptions, 'signal'>) => {
    const response = await execute('GET', path, { ...opts, query })
    if (!response.ok) return failWith(response)
    return { blob: await response.blob(), filename: filenameFrom(response) }
  },
  /** multipart/form-data (загрузки файлов). */
  upload: <T>(path: string, form: FormData, method: 'POST' | 'PATCH' | 'PUT' = 'POST') =>
    request<T>(method, path, { form }),
}
