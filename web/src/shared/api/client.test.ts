import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { getAccess, getRefresh, setTokens } from '../auth/tokens'
import { api } from './client'
import { ApiError } from './errors'
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
})
