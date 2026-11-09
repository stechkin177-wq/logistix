import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { setTokens, getAccess } from '../shared/auth/tokens'
import { mockFetch } from '../test/fetchMock'
import { BRANDING, makeSession } from '../test/fixtures'
import { renderApp } from '../test/renderApp'
import { ALL_PERMISSIONS } from '../test/permissions'

const base = (session = makeSession()) =>
  [
    ['GET', /^\/api\/branding\//, { body: BRANDING }],
    ['GET', '/api/company/branding/', { body: BRANDING }],
    ['GET', '/api/session/', { body: session }],
    ['GET', '/api/dashboard/summary/', { status: 403, body: { detail: 'x', code: 'permission_denied' } }],
  ] as Parameters<typeof mockFetch>[0]

describe('Sidebar', () => {
  it('показывает меню по правам и модулям', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    const perms = ALL_PERMISSIONS.filter((p) => p !== 'users.view')
    mockFetch(base(makeSession({ permissions: perms })))
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).getByText('Клиенты')).toBeInTheDocument()
    expect(within(nav).getByText('Роли и права')).toBeInTheDocument()
    expect(within(nav).queryByText('Пользователи')).not.toBeInTheDocument()
  })

  it('«Ещё»: корзина и справочники свёрнуты, открываются по клику и открыты на своей странице', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([...base(), ['GET', /^\/api\/trash\//, { body: { count: 0, next: null, previous: null, results: [] } }]])
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByRole('link', { name: 'Корзина' })).not.toBeInTheDocument()
    await userEvent.click(within(nav).getByRole('button', { name: /Ещё/ }))
    expect(within(nav).getByRole('link', { name: 'Корзина' })).toHaveAttribute('href', '/trash')
    expect(within(nav).getByRole('link', { name: 'Справочники' })).toHaveAttribute('href', '/settings/handbooks')
  })

  it('на странице корзины группа «Ещё» открыта сама', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch([...base(), ['GET', /^\/api\/trash\//, { body: { count: 0, next: null, previous: null, results: [] } }]])
    renderApp('/trash')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(await within(nav).findByRole('link', { name: 'Корзина' })).toBeInTheDocument()
  })

  it('без модуля logistics прячет клиентов и заказы', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch(base(makeSession({ modules: ['fleet', 'finance'] })))
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByText('Клиенты')).not.toBeInTheDocument()
    expect(within(nav).queryByText('Заказы')).not.toBeInTheDocument()
    expect(within(nav).getByText('Финансы')).toBeInTheDocument()
    expect(within(nav).queryByText('Документы')).not.toBeInTheDocument() // отдельный модуль documents
  })

  it('переключатель компании вызывает switch-company и сбрасывает кэш', async () => {
    setTokens({ access: 'old', refresh: 'oldr' })
    let current = 10
    const m = mockFetch([
      ...base(),
      [
        'POST',
        '/api/auth/switch-company/',
        (call) => {
          current = (call.body as { company_id: number }).company_id
          return { body: { access: 'new-access', refresh: 'new-refresh', companies: [] } }
        },
      ],
    ])
    // сессия зависит от выбранной компании
    const sessions = {
      10: makeSession({ companies: [{ id: 10, name: 'Альфа' }, { id: 20, name: 'Бета' }] }),
      20: makeSession({
        company: { id: 20, name: 'Бета', timezone: 'Asia/Almaty', language: 'ru' },
        companies: [{ id: 10, name: 'Альфа' }, { id: 20, name: 'Бета' }],
      }),
    }
    const original = m.fn.getMockImplementation()!
    m.fn.mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : ''
      if (url === '/api/session/') {
        return new Response(JSON.stringify(sessions[current as 10 | 20]), { status: 200 })
      }
      return original(input, init)
    })
    renderApp('/')
    const select = await screen.findByLabelText('Компания')
    await userEvent.setup().selectOptions(select, 'Бета')
    await waitFor(() => {
      expect(getAccess()).toBe('new-access')
    })
    const call = m.calls.find((c) => c.path === '/api/auth/switch-company/')
    expect(call?.body).toEqual({ company_id: 20 })
    expect(window.sessionStorage.getItem('logistix.refresh')).toBe('new-refresh')
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLSelectElement>('Компания').value).toBe('20')
    })
  })

  it('с одной компанией показывает название без выпадающего списка', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch(base())
    renderApp('/')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(screen.queryByLabelText('Компания')).not.toBeInTheDocument()
    expect(screen.getAllByText('Альфа').length).toBeGreaterThan(0)
  })

  it('выход очищает токены и ведёт на /login', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    mockFetch(base())
    const { router } = renderApp('/')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Выйти' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/login')
    })
    expect(getAccess()).toBeNull()
    expect(window.sessionStorage.getItem('logistix.refresh')).toBeNull()
  })

  it('оформление компании берётся из сессии даже без company.view', async () => {
    setTokens({ access: 'a', refresh: 'r' })
    const perms = ALL_PERMISSIONS.filter((p) => p !== 'company.view')
    const m = mockFetch(
      base(
        makeSession({
          permissions: perms,
          branding: { app_name: 'Мой бренд', logo_url: null, primary_color: '#aa0000', theme: 'light' },
        }),
      ),
    )
    renderApp('/')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    await waitFor(() => {
      expect(document.documentElement.style.getPropertyValue('--brand-500')).toBe('#aa0000')
    })
    expect(document.title).toBe('Мой бренд')
    expect(screen.getAllByText('Мой бренд').length).toBeGreaterThan(0)
    expect(m.calls.some((c) => c.path === '/api/company/branding/')).toBe(false)
  })
})
