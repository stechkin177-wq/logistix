import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { clearTokens, getAccess, getRefresh, setTokens } from '../auth/tokens'
import { api } from './client'
import { ApiError, buildApiError } from './errors'
import { onApiEvent } from './events'

beforeEach(() => {
  setTokens({ access: 'old-access', refresh: 'the-refresh' })
})

describe('api client', () => {
  it('добавляет Bearer-токен и JSON-тело', async () => {
    const m = mockFetch([['POST', '/api/clients/', { status: 201, body: { id: 1 } }]])
    const res = await api.post<{ id: number }>('/clients/', { name: 'ТОО' })
    expect(res).toEqual({ id: 1 })
    expect(m.calls[0]?.headers.Authorization).toBe('Bearer old-access')
    expect(m.calls[0]?.headers['Content-Type']).toBe('application/json')
    expect(m.calls[0]?.body).toEqual({ name: 'ТОО' })
  })

  it('собирает query и не кладёт токен в URL', async () => {
    const m = mockFetch([['GET', /^\/api\/orders\//, { body: [] }]])
    await api.get('/orders/', { page: 2, q: 'а б', empty: '', none: undefined })
    expect(m.calls[0]?.path).toBe('/api/orders/?page=2&q=%D0%B0+%D0%B1')
    expect(m.calls[0]?.path).not.toContain('old-access')
  })

  it('два параллельных 401 дают ОДНО обновление и по одному повтору', async () => {
    let refreshes = 0
    const m = mockFetch([
      [
        'GET',
        /^\/api\/(a|b)\/$/,
        (call) =>
          call.headers.Authorization === 'Bearer new-access'
            ? { body: { ok: true } }
            : { status: 401, body: { detail: 'expired', code: 'token_not_valid' } },
      ],
      [
        'POST',
        '/api/auth/refresh/',
        async () => {
          refreshes++
          await new Promise((r) => setTimeout(r, 10))
          return { body: { access: 'new-access' } }
        },
      ],
    ])
    const [a, b] = await Promise.all([api.get('/a/'), api.get('/b/')])
    expect(a).toEqual({ ok: true })
    expect(b).toEqual({ ok: true })
    expect(refreshes).toBe(1)
    expect(m.count('GET', '/api/a/')).toBe(2) // исходный + один повтор
    expect(m.count('GET', '/api/b/')).toBe(2)
    expect(getAccess()).toBe('new-access')
    expect(m.calls.find((c) => c.path === '/api/auth/refresh/')?.body).toEqual({ refresh: 'the-refresh' })
  })

  it('при неудачном обновлении чистит сессию, сообщает о выходе и бросает 401', async () => {
    mockFetch([
      ['GET', '/api/a/', { status: 401, body: { detail: 'x', code: 'token_not_valid' } }],
      ['POST', '/api/auth/refresh/', { status: 401, body: { detail: 'bad', code: 'token_not_valid' } }],
    ])
    const onLogout = vi.fn()
    const off = onApiEvent('logout', onLogout)
    await expect(api.get('/a/')).rejects.toMatchObject({ status: 401 })
    off()
    expect(onLogout).toHaveBeenCalledTimes(1)
    expect(getAccess()).toBeNull()
    expect(getRefresh()).toBeNull()
  })

  it('без access после перезагрузки сначала обновляет токен', async () => {
    setTokens({ access: 'x', refresh: 'r' })
    // имитируем перезагрузку: access в памяти пропал, refresh остался
    const { clearTokens } = await import('../auth/tokens')
    clearTokens()
    window.sessionStorage.setItem('logistix.refresh', 'r')
    const m = mockFetch([
      ['POST', '/api/auth/refresh/', { body: { access: 'fresh' } }],
      ['GET', '/api/session/', (call) => (call.headers.Authorization === 'Bearer fresh' ? { body: { ok: 1 } } : { status: 401 })],
    ])
    await expect(api.get('/session/')).resolves.toEqual({ ok: 1 })
    expect(m.count('GET', '/api/session/')).toBe(1)
  })

  it('401 при входе (auth: false) не запускает обновление', async () => {
    const m = mockFetch([
      ['POST', '/api/auth/login/', { status: 401, body: { detail: 'Неверный логин или пароль', code: 'authentication_failed' } }],
    ])
    await expect(api.post('/auth/login/', { login: 'a', password: 'b' }, { auth: false })).rejects.toMatchObject({
      status: 401,
      code: 'authentication_failed',
    })
    expect(m.count('POST', '/api/auth/refresh/')).toBe(0)
  })

  it('отображает {detail, code} в ApiError', async () => {
    mockFetch([['GET', '/api/x/', { status: 403, body: { detail: 'Модуль не подключён', code: 'module_disabled' } }]])
    const error = await api.get('/x/').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'module_disabled', detail: 'Модуль не подключён', fields: {} })
  })

  it('отображает словарь ошибок полей DRF', async () => {
    mockFetch([['POST', '/api/x/', { status: 400, body: { name: ['Обязательное поле.'], phone: ['Плохой', 'Очень'] } }]])
    const error = await api.post('/x/', {}).catch((e: unknown) => e)
    expect(error).toMatchObject({
      status: 400,
      code: 'validation_error',
      fields: { name: ['Обязательное поле.'], phone: ['Плохой', 'Очень'] },
    })
  })

  it('подписка заблокирована и readonly рассылают события', async () => {
    mockFetch([
      ['GET', '/api/b/', { status: 403, body: { detail: 'x', code: 'subscription_blocked' } }],
      ['POST', '/api/r/', { status: 403, body: { detail: 'x', code: 'subscription_readonly' } }],
    ])
    const blocked = vi.fn()
    const readonly = vi.fn()
    const offs = [onApiEvent('blocked', blocked), onApiEvent('readonly', readonly)]
    await api.get('/b/').catch(() => undefined)
    await api.post('/r/', {}).catch(() => undefined)
    offs.forEach((off) => {
      off()
    })
    expect(blocked).toHaveBeenCalledTimes(1)
    expect(readonly).toHaveBeenCalledTimes(1)
  })

  it('сбой сети - ApiError status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.get('/x/')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('204 возвращает undefined; multipart не ставит Content-Type', async () => {
    const m = mockFetch([
      ['DELETE', '/api/x/1/', { status: 204 }],
      ['POST', '/api/up/', { body: { ok: true } }],
    ])
    await expect(api.delete('/x/1/')).resolves.toBeUndefined()
    await api.upload('/up/', new FormData())
    expect(m.calls[1]?.headers['Content-Type']).toBeUndefined()
  })

  it('сеть или 5xx при обновлении: токены целы, ошибка повторяемая, выхода нет', async () => {
    const onLogout = vi.fn()
    const off = onApiEvent('logout', onLogout)
    const unauthorized = { status: 401, body: { detail: 'x', code: 'token_not_valid' } }
    mockFetch([
      ['GET', '/api/a/', unauthorized],
      ['POST', '/api/auth/refresh/', { status: 503, body: { detail: 'down' } }],
    ])
    await expect(api.get('/a/')).rejects.toMatchObject({ status: 503, code: 'refresh_unavailable' })
    expect(getRefresh()).toBe('the-refresh')
    expect(getAccess()).toBe('old-access')

    // сеть
    const base = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : ''
      if (url === '/api/auth/refresh/') return Promise.reject(new TypeError('Failed to fetch'))
      return Promise.resolve(new Response(JSON.stringify(unauthorized.body), { status: 401 }))
    })
    vi.stubGlobal('fetch', base)
    await expect(api.get('/a/')).rejects.toMatchObject({ status: 0, code: 'network_error' })
    expect(getRefresh()).toBe('the-refresh')
    off()
    expect(onLogout).not.toHaveBeenCalled()
  })

  it.each([400, 403])('обновление отклонено с %i: сессия очищена', async (status) => {
    mockFetch([
      ['GET', '/api/a/', { status: 401, body: { detail: 'x' } }],
      ['POST', '/api/auth/refresh/', { status, body: { detail: 'bad' } }],
    ])
    await expect(api.get('/a/')).rejects.toMatchObject({ status: 401 })
    expect(getRefresh()).toBeNull()
  })
})

describe('запоздавший refresh не перезаписывает новую сессию', () => {
  function pendingRefresh(refreshReply: { status: number; body: unknown }) {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    let started = false
    const m = mockFetch([
      [
        'GET',
        '/api/a/',
        (call) =>
          call.headers.Authorization === 'Bearer B-access'
            ? { body: { ok: 'B' } }
            : { status: 401, body: { detail: 'expired', code: 'token_not_valid' } },
      ],
      [
        'POST',
        '/api/auth/refresh/',
        async () => {
          started = true
          await gate
          return refreshReply
        },
      ],
    ])
    return { m, release, started: () => started }
  }

  it('выход во время refresh: токены остаются очищенными, sessionStorage пуст', async () => {
    const { release, started } = pendingRefresh({ status: 200, body: { access: 'late-access', refresh: 'late-refresh' } })
    const onLogout = vi.fn()
    const off = onApiEvent('logout', onLogout)
    const request = api.get('/a/').catch((e: unknown) => e)
    await vi.waitFor(() => {
      expect(started()).toBe(true)
    })
    clearTokens() // пользователь вышел
    release()
    await request
    off()
    expect(getAccess()).toBeNull()
    expect(window.sessionStorage.getItem('logistix.refresh')).toBeNull()
    expect(getRefresh()).toBeNull()
    expect(onLogout).not.toHaveBeenCalled()
  })

  it('смена компании во время refresh старой: побеждают новые токены, запрос повторяется с ними', async () => {
    const { release, started } = pendingRefresh({ status: 200, body: { access: 'A-late', refresh: 'A-late-refresh' } })
    const request = api.get('/a/')
    await vi.waitFor(() => {
      expect(started()).toBe(true)
    })
    setTokens({ access: 'B-access', refresh: 'B-refresh' }) // switch-company
    release()
    await expect(request).resolves.toEqual({ ok: 'B' })
    expect(getAccess()).toBe('B-access')
    expect(getRefresh()).toBe('B-refresh')
  })

  it('отклонённый refresh старой компании не очищает новую сессию', async () => {
    const { release, started } = pendingRefresh({ status: 401, body: { detail: 'old', code: 'token_not_valid' } })
    const onLogout = vi.fn()
    const off = onApiEvent('logout', onLogout)
    const request = api.get('/a/')
    await vi.waitFor(() => {
      expect(started()).toBe(true)
    })
    setTokens({ access: 'B-access', refresh: 'B-refresh' })
    release()
    await expect(request).resolves.toEqual({ ok: 'B' })
    off()
    expect(getRefresh()).toBe('B-refresh')
    expect(getAccess()).toBe('B-access')
    expect(onLogout).not.toHaveBeenCalled()
  })
})

describe('ошибки валидации DRF', () => {
  it('вложенные пути и ValidationError-список', () => {
    const nested = buildApiError(400, { consignments: [{}, { points: [{}, { city: ['Укажите город'] }] }], client: ['Обязательное поле.'] })
    expect(nested.fields).toEqual({ 'consignments.1.points.1.city': ['Укажите город'], client: ['Обязательное поле.'] })
    const list = buildApiError(400, ['Слишком много заказов'])
    expect(list.detail).toBe('Слишком много заказов')
    expect(list.fields).toEqual({ non_field_errors: ['Слишком много заказов'] })
  })
})

describe('отмена и скачивание', () => {
  it('abort-сигнал отменяет запрос и не превращается в network_error', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => { reject(new DOMException('aborted', 'AbortError')) })
    })))
    const controller = new AbortController()
    const pending = api.get('/clients/', undefined, { signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('download: blob, имя из Content-Disposition, Bearer и ошибка 400', async () => {
    setTokens({ access: 'tok', refresh: 'r' })
    const fn = vi.fn<typeof fetch>()
    fn.mockResolvedValue(new Response('BYTES', { status: 200, headers: { 'Content-Disposition': 'attachment; filename="orders-2026-10-31.xlsx"' } }))
    vi.stubGlobal('fetch', fn)
    const result = await api.download('/orders/export/', { q: 'x' })
    expect(result.filename).toBe('orders-2026-10-31.xlsx')
    expect(await result.blob.text()).toBe('BYTES')
    expect(fn.mock.calls[0]?.[0]).toBe('/api/orders/export/?q=x')
    expect((fn.mock.calls[0]?.[1]?.headers as Record<string, string>).Authorization).toBe('Bearer tok')

    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(['Слишком много заказов']), { status: 400 }))))
    await expect(api.download('/orders/export/')).rejects.toMatchObject({ status: 400, detail: 'Слишком много заказов' })
  })
})
