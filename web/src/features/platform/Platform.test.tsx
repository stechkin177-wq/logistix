import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeSession, page } from '../../test/fixtures'
import { loggedIn, platformLoggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const PLAN = (over = {}) => ({
  code: 'start', name: 'Старт', description: '', billing_type: 'monthly', price: '0.00', currency: 'KZT', sort_order: 10,
  status: 'active', is_default: true, limits: { max_vehicles: 5 }, modules: ['logistics', 'fleet'], features: {},
  archived_at: null, free_period_days: 365, limit_warn_percent: 80, subscriptions_count: 3, ...over,
})
const CATALOG = {
  modules: [
    { code: 'logistics', name: 'Перевозки', description: '', requires: [], status: 'available' },
    { code: 'finance', name: 'Финансы', description: '', requires: ['logistics'], status: 'available' },
    { code: 'fleet', name: 'Автопарк', description: '', requires: [], status: 'available' },
  ],
  features: [
    { code: 'multi_branch', module: 'core', kind: 'bool', name: 'Несколько филиалов', description: '' },
    { code: 'analytics_level', module: 'analytics', kind: 'level', name: 'Аналитика', description: '', levels: ['basic', 'full'] },
  ],
  limits: [
    { code: 'max_vehicles', name: 'Техника', unit: 'ед.', scope: 'total', enforced: true },
    { code: 'max_orders_per_month', name: 'Заказы в месяц', unit: 'шт.', scope: 'month', enforced: true },
  ],
}
const base: MockRoutes = [
  ['GET', '/api/platform/plans/', { body: [PLAN(), PLAN({ code: 'pro', name: 'Профи', status: 'draft', is_default: false, subscriptions_count: 0, sort_order: 20 })] }],
  ['GET', '/api/platform/catalog/', { body: CATALOG }],
]

describe('Панель платформы', () => {
  it('в меню компании нет платформенных разделов', async () => {
    loggedIn([...base])
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByText('Подписки компаний')).not.toBeInTheDocument()
    expect(within(nav).queryByText('История изменений')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Центр управления' })).not.toBeInTheDocument()
  })

  it('у платформенной роли в меню компании есть переход в Центр управления', async () => {
    loggedIn([...base], { session: { user: { id: 1, email: 'a@x.kz', phone: null, full_name: 'А', platform_role: 'owner' } } })
    renderApp('/')
    expect(await screen.findByRole('button', { name: 'Центр управления' })).toBeInTheDocument()
  })

  it('Центр управления: свой интерфейс с разделами платформы, без меню компании', async () => {
    platformLoggedIn([...base])
    renderApp('/platform')
    const nav = await screen.findByRole('navigation', { name: 'Центр управления' })
    expect(within(nav).getByText('Тарифы')).toBeInTheDocument()
    expect(within(nav).getByText('Подписки компаний')).toBeInTheDocument()
    expect(within(nav).getByText('История изменений')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Основное меню' })).not.toBeInTheDocument()
    expect(await screen.findByText('Владелец · Владелец платформы')).toBeInTheDocument()
  })

  it('платформенный контекст не открывает страницы компании', async () => {
    platformLoggedIn([...base])
    const { router } = renderApp('/orders')
    await screen.findByRole('navigation', { name: 'Центр управления' })
    expect(router.state.location.pathname).toBe('/platform/plans')
  })

  it('пользователь компании не попадает в Центр управления', async () => {
    const m = loggedIn([...base])
    const { router } = renderApp('/platform/plans')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(router.state.location.pathname).toBe('/')
    expect(m.calls.some((c) => c.path === '/api/platform/plans/')).toBe(false)
  })

  it('переход в компанию из Центра управления и обратно меняет контекст', async () => {
    const m = platformLoggedIn(
      [
        ...base,
        ['POST', '/api/auth/switch-company/', { body: { access: 'c', refresh: 'cr', context: 'company', companies: [] } }],
        ['GET', '/api/session/', { body: makeSession() }],
      ],
      { companies: [{ id: 10, name: 'Альфа' }] },
    )
    const { router } = renderApp('/platform/plans')
    const select = await screen.findByLabelText('Открыть компанию…')
    await userEvent.selectOptions(select, '10')
    await waitFor(() => { expect(router.state.location.pathname).toBe('/') })
    expect(m.calls.find((c) => c.path === '/api/auth/switch-company/')!.body).toEqual({ company_id: 10 })
    expect(await screen.findByRole('navigation', { name: 'Основное меню' })).toBeInTheDocument()
  })

  it('список тарифов: статусы, по умолчанию, действия и смена порядка', async () => {
    const m = platformLoggedIn([...base, ['POST', '/api/platform/plans/reorder/', { body: [] }], ['POST', '/api/platform/plans/pro/publish/', { body: PLAN() }]])
    renderApp('/platform/plans')
    const table = await screen.findByRole('table')
    expect(await within(table).findByText('Старт')).toBeInTheDocument()
    expect(within(table).getByText('по умолчанию')).toBeInTheDocument()
    expect(within(table).getByText('черновик')).toBeInTheDocument()
    // у тарифа по умолчанию нет «В архив» и «Удалить»
    expect(within(table).getAllByRole('button', { name: 'В архив' })).toHaveLength(1)
    await userEvent.click(within(table).getByRole('button', { name: 'Ниже: Старт' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/platform/plans/reorder/')).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/platform/plans/reorder/')!.body).toEqual({ codes: ['pro', 'start'] })
    await userEvent.click(within(table).getByRole('button', { name: 'Опубликовать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/platform/plans/pro/publish/')).toBe(true) })
  })

  it('создание тарифа: модули тянут зависимости, лимиты и функции уходят одним запросом', async () => {
    const m = platformLoggedIn([...base, ['POST', '/api/platform/plans/', { status: 201, body: PLAN({ code: 'gold' }) }]])
    renderApp('/platform/plans')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый тариф' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Код/), 'gold')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Золото')
    await userEvent.click(within(drawer).getByRole('tab', { name: 'Модули и функции' }))
    await userEvent.click(await within(drawer).findByLabelText(/Финансы/))  // тянет «Перевозки»
    expect(within(drawer).getByLabelText(/Перевозки/)).toBeChecked()
    expect(within(drawer).getByLabelText('Аналитика')).toBeDisabled()  // нужен модуль analytics
    await userEvent.click(within(drawer).getByLabelText('Несколько филиалов'))
    await userEvent.click(within(drawer).getByRole('tab', { name: 'Лимиты' }))
    await userEvent.type(await within(drawer).findByLabelText('Техника'), '7')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/platform/plans/')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'POST' && c.path === '/api/platform/plans/')!.body as Record<string, unknown>
    expect(body).toMatchObject({ code: 'gold', name: 'Золото', features: { multi_branch: true }, limits: { max_vehicles: 7, max_orders_per_month: null } })
    expect((body.modules as string[]).sort()).toEqual(['finance', 'logistics'])
  })

  it('снятие модуля убирает зависящие от него модули', async () => {
    platformLoggedIn([...base])
    renderApp('/platform/plans')
    await userEvent.click(await screen.findByRole('button', { name: 'Старт (start)' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('tab', { name: 'Модули и функции' }))
    await userEvent.click(await within(drawer).findByLabelText(/Финансы/))
    expect(within(drawer).getByLabelText(/Перевозки/)).toBeChecked()
    await userEvent.click(within(drawer).getByLabelText(/Перевозки/))
    expect(within(drawer).getByLabelText(/Финансы/)).not.toBeChecked()  // зависимый модуль снят
  })

  it('ошибка сервера при сохранении показывается в панели', async () => {
    platformLoggedIn([...base, ['PATCH', '/api/platform/plans/start/', { status: 400, body: { detail: 'В тариф нужно добавить зависимости: finance -> logistics', code: 'plan_modules_incomplete' } }]])
    renderApp('/platform/plans')
    await userEvent.click(await screen.findByRole('button', { name: 'Старт (start)' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByText(/нужно добавить зависимости/)).toBeInTheDocument()
  })

  it('подписка компании: анализ последствий и смена тарифа с периодом', async () => {
    const SUB = { company: 7, plan: 'start', status: 'active', is_free_period: true, starts_at: '2026-01-01T00:00:00Z', ends_at: '2027-01-01T00:00:00Z',
      current_period: { plan: 'start', reason: 'start', starts_at: '2026-01-01T00:00:00Z', ends_at: '2027-01-01T00:00:00Z', price: '0.00', currency: 'KZT', is_free: true },
      periods: [{ plan: 'start', reason: 'start', starts_at: '2026-01-01T00:00:00Z', ends_at: '2027-01-01T00:00:00Z', price: '0.00', currency: 'KZT' }] }
    const PREVIEW = { from_plan: 'start', to_plan: 'pro', price: { current_period: '0.00', new: '500.00', currency: 'KZT' }, lost_modules: ['fleet'], gained_modules: ['finance'],
      lost_features: [], gained_features: [], limits_exceeded: [{ code: 'max_vehicles', name: 'Техника', usage: 4, old_limit: 5, new_limit: 2 }], limits_tightened: [] }
    const m = platformLoggedIn([
      ['GET', /^\/api\/platform\/companies\/\?/, { body: page([{ id: 7, name: 'ТОО Альфа', plan: 'start', plan_name: 'Старт', status: 'active', is_free_period: true, ends_at: '2027-01-01T00:00:00Z' }]) }],
      ['GET', '/api/platform/subscriptions/7/', { body: SUB }],
      ['GET', /^\/api\/platform\/subscriptions\/7\/change-plan\/preview\//, { body: PREVIEW }],
      ['POST', '/api/platform/subscriptions/7/change-plan/', { body: SUB }],
      ...base,
    ])
    renderApp('/platform/companies')
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Альфа' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.selectOptions(await within(drawer).findByLabelText('Новый тариф'), 'pro')
    const impact = await within(drawer).findByRole('group', { name: 'Последствия смены' })
    expect(within(impact).getByText(/Закроются модули.*fleet/)).toBeInTheDocument()
    expect(within(impact).getByText(/Техника: использовано 4, новый лимит 2 — данные сохранятся/)).toBeInTheDocument()
    await userEvent.selectOptions(within(drawer).getByLabelText('Период'), 'restart')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Применить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/platform/subscriptions/7/change-plan/' && c.method === 'POST')).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/platform/subscriptions/7/change-plan/' && c.method === 'POST')!.body).toEqual({ plan: 'pro', period: 'restart' })
  })

  it('журнал изменений: кто, когда и что изменено (было → стало)', async () => {
    platformLoggedIn([
      ['GET', /^\/api\/platform\/history\//, { body: page([{ id: 1, kind: 'plan', key: 'start', action: 'update', actor: 'admin@x.kz', created_at: '2026-11-09T07:00:00Z', changes: { price: ['0.00', '500.00'] } }]) }],
    ])
    renderApp('/platform/history')
    expect(await screen.findByText('admin@x.kz')).toBeInTheDocument()
    expect(screen.getByText('Тариф: start')).toBeInTheDocument()
    expect(screen.getByText('изменение')).toBeInTheDocument()
    expect(screen.getByText(/0\.00 → 500\.00/)).toBeInTheDocument()
  })
})
