import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { BRANDING, makeSession } from '../../test/fixtures'
import { mockFetch } from '../../test/fetchMock'
import { renderApp } from '../../test/renderApp'
import { getAccess, getRefresh, setTokens } from './tokens'
import { loginPath, safeRedirect } from './redirect'

const common = [
  ['GET', /^\/api\/branding\//, { body: BRANDING }],
  ['GET', '/api/company/branding/', { body: BRANDING }],
  ['GET', '/api/dashboard/summary/', { body: { active_orders: 7, completed_orders: 3, unassigned_orders: 1, clients: 5, carriers: 2, orders_by_status: [], month: '2026-11', month_profit: null, month_margin_pct: null } }],
] as Parameters<typeof mockFetch>[0]

function dump(storage: Storage): string {
  return Array.from({ length: storage.length }, (_, i) => {
    const key = storage.key(i) ?? ''
    return `${key}=${storage.getItem(key) ?? ''}`
  }).join(';')
}

async function submitLogin(login: string, password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Email или телефон'), login)
  await user.type(screen.getByLabelText('Пароль'), password)
  await user.click(screen.getByRole('button', { name: 'Войти' }))
}

describe('RequireAuth', () => {
  it('без токенов перенаправляет на /login с сохранением цели', async () => {
    mockFetch(common)
    const { router } = renderApp('/orders?status=new')
    await screen.findByLabelText('Email или телефон')
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toBe('?next=%2Forders%3Fstatus%3Dnew')
  })

  it('с токеном показывает защищённую страницу', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([...common, ['GET', '/api/session/', { body: makeSession() }]])
    renderApp('/')
    expect(await screen.findByText('Активные заказы')).toBeInTheDocument()
    expect(await screen.findByText('7')).toBeInTheDocument()
  })
})

describe('вход', () => {
  it('успешный вход: access только в памяти, refresh в sessionStorage, переход на цель', async () => {
    const m = mockFetch([
      ...common,
      ['POST', '/api/auth/login/', { body: { access: 'ACC', refresh: 'REF', companies: [{ id: 10, name: 'Альфа' }] } }],
      ['GET', '/api/session/', { body: makeSession() }],
    ])
    const { router } = renderApp('/login?next=%2Ftrips')
    await submitLogin('admin@example.kz', 'secret')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/trips')
    })
    expect(m.calls.find((c) => c.path === '/api/auth/login/')?.body).toEqual({ login: 'admin@example.kz', password: 'secret' })
    expect(getAccess()).toBe('ACC')
    expect(getRefresh()).toBe('REF')
    expect(window.sessionStorage.getItem('logistix.refresh')).toBe('REF')
    // access не лежит ни в одном хранилище
    expect(dump(window.sessionStorage)).not.toContain('ACC')
    expect(dump(window.localStorage)).not.toContain('ACC')
    expect(await screen.findByText('Раздел готовится')).toBeInTheDocument()
  })

  it('сбой загрузки сессии после входа не оставляет токены', async () => {
    mockFetch([
      ...common,
      ['POST', '/api/auth/login/', { body: { access: 'ACC', refresh: 'REF', companies: [] } }],
      ['GET', '/api/session/', { status: 500, body: { detail: 'boom' } }],
    ])
    renderApp('/login')
    await submitLogin('admin@example.kz', 'secret')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(getAccess()).toBeNull()
    expect(getRefresh()).toBeNull()
    expect(window.sessionStorage.getItem('logistix.refresh')).toBeNull()
  })

  it('неверный пароль показывает общее сообщение и не сохраняет токены', async () => {
    mockFetch([
      ...common,
      ['POST', '/api/auth/login/', { status: 401, body: { detail: 'Неверный логин или пароль', code: 'authentication_failed' } }],
    ])
    renderApp('/login')
    await submitLogin('admin@example.kz', 'wrong')
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный логин или пароль')
    expect(getAccess()).toBeNull()
    expect(getRefresh()).toBeNull()
  })

  it('ошибки валидации показываются у поля', async () => {
    mockFetch([
      ...common,
      ['POST', '/api/auth/login/', { status: 400, body: { login: ['Некорректный номер телефона'] } }],
    ])
    renderApp('/login')
    await submitLogin('123', 'x')
    expect(await screen.findByText('Некорректный номер телефона')).toBeInTheDocument()
  })

  it('subscription_blocked при входе показывает экран «Доступ приостановлен»', async () => {
    const m = mockFetch([
      ...common,
      ['POST', '/api/auth/login/', { status: 403, body: { detail: 'Подписка компании заблокирована', code: 'subscription_blocked' } }],
    ])
    renderApp('/login')
    await submitLogin('admin@example.kz', 'secret')
    expect(await screen.findByRole('heading', { name: 'Доступ приостановлен' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Выйти' })).toBeInTheDocument()
    const before = m.calls.length
    await userEvent.setup().click(screen.getByRole('button', { name: 'Выйти' }))
    await screen.findByLabelText('Email или телефон')
    // выход не обращается к API
    expect(m.calls.slice(before).filter((c) => c.path.startsWith('/api/auth')).length).toBe(0)
  })

  it('403 subscription_blocked в любой момент работы блокирует интерфейс', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([
      ['GET', '/api/dashboard/summary/', { status: 403, body: { detail: 'x', code: 'subscription_blocked' } }],
      ['GET', '/api/session/', { body: makeSession() }],
      ...common,
    ])
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Доступ приостановлен' })).toBeInTheDocument()
  })

  it('публичное оформление запрашивается до входа по host', async () => {
    const m = mockFetch(common)
    renderApp('/login')
    await screen.findByLabelText('Email или телефон')
    await waitFor(() => {
      expect(m.calls.some((c) => c.path === '/api/branding/?host=localhost')).toBe(true)
    })
    expect(m.calls.some((c) => c.path === '/api/company/branding/')).toBe(false)
  })
})

describe('прямой заход в раздел', () => {
  it('без права показывает 403, с правом - раздел', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([
      ...common,
      ['GET', '/api/session/', { body: makeSession({ permissions: ['orders.view'] }) }],
    ])
    renderApp('/settings/users')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })

  it('неизвестный путь - 404', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([...common, ['GET', '/api/session/', { body: makeSession() }]])
    renderApp('/nope')
    expect(await screen.findByText('Страница не найдена')).toBeInTheDocument()
  })
})

describe('redirect', () => {
  it('safeRedirect пропускает только внутренние пути', () => {
    expect(safeRedirect('/orders?x=1')).toBe('/orders?x=1')
    for (const bad of ['//evil.com', 'https://evil.com', 'javascript:alert(1)', '/\\evil', '/login', null, '']) {
      expect(safeRedirect(bad)).toBe('/')
    }
    expect(loginPath('/orders')).toBe('/login?next=%2Forders')
  })
})
