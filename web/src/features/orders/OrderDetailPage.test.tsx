import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, ORDER_STATUSES, handbookBody, makeLine, makeOrder } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const common = [
  ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
  ['GET', '/api/users/', { body: [{ user_id: 1, full_name: 'Админ Админов', email: null, phone: null, is_active: true }] }],
  ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
] as MockRoutes

const LINES = page([makeLine(), makeLine({ id: 101, title: 'Фрахт', is_base: false, income: '0.00', expense: '100000.00' })])

describe('Карточка заказа: рейс одной кнопкой', () => {
  it('«Создать рейс» отправляет POST /trips/ со всеми грузами заказа и открывает карточку рейса', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['POST', '/api/trips/', { status: 201, body: { id: 90, number: 'ORD-2026-00005-1' } }],
      ['GET', /^\/api\/trips\//, { body: page([]) }],
      ['GET', '/api/handbooks/?code=trip_status', { body: handbookBody('trip_status', []) }],
      ...common,
    ])
    const { router } = renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Создать рейс' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/trips/' && c.method === 'POST')?.body).toMatchObject({ consignments: [makeOrder().consignments[0]!.id] }) })
    await waitFor(() => { expect(router.state.location.pathname + router.state.location.search).toBe('/trips/90') })
  })

  it('без права trips.create кнопки «Создать рейс» нет', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder() }], ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trips.create') } })
    renderApp('/orders/5')
    await screen.findByRole('heading', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('button', { name: 'Создать рейс' })).not.toBeInTheDocument()
  })

  it('заказ без грузов: кнопка отключена', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder({ consignments: [] }) }], ...common])
    renderApp('/orders/5')
    expect(await screen.findByRole('button', { name: 'Создать рейс' })).toBeDisabled()
  })
})

describe('Карточка заказа', () => {
  it('шапка: номер, статус, клиент; обзор с полями', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder() }], ...common])
    renderApp('/orders/5')
    expect(await screen.findByRole('heading', { name: 'ORD-2026-00005' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ТОО Ромашка' })).toHaveAttribute('href', '/clients/7')
    expect(screen.getByText('Д-1')).toBeInTheDocument()
    // ставка видна и в сводке над вкладками, и в обзоре
    expect((await screen.findAllByText(/^250\s000,00\sKZT$/)).length).toBeGreaterThanOrEqual(2)
  })

  it('смена статуса: POST /status/ и обновление карточки', async () => {
    let order = makeOrder()
    const m = loggedIn([
      ['POST', '/api/orders/5/status/', (call) => { order = makeOrder({ status: (call.body as { status: number }).status, status_name: 'В работе' }); return { body: order } }],
      ['GET', '/api/orders/5/', () => ({ body: order })],
      ...common,
    ])
    renderApp('/orders/5')
    const select = await screen.findByRole('combobox', { name: 'Статус заказа ORD-2026-00005' })
    await userEvent.selectOptions(select, 'В работе')
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 2 }) })
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'GET' && c.path === '/api/orders/5/').length).toBeGreaterThan(1) })
    await waitFor(() => { expect(screen.getByRole('combobox', { name: 'Статус заказа ORD-2026-00005' })).toHaveValue('2') })
  })

  it('отказ смены статуса показывается уведомлением', async () => {
    loggedIn([
      ['POST', '/api/orders/5/status/', { status: 403, body: { detail: 'x', code: 'subscription_readonly' } }],
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ...common,
    ])
    renderApp('/orders/5')
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: /Статус заказа/ }), 'В работе')
    expect((await screen.findAllByText(/только просмотр/)).length).toBeGreaterThan(0)
  })

  it('правка: PATCH без status/number/consignments', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['PATCH', '/api/orders/5/', { body: makeOrder({ contract_number: 'Д-2' }) }],
      ...common,
    ])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Изменить' }))
    const input = await screen.findByLabelText('Номер договора')
    await userEvent.clear(input)
    await userEvent.type(input, 'Д-2')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>
    expect(body.contract_number).toBe('Д-2')
    for (const forbidden of ['status', 'number', 'consignments', 'completed_at']) expect(body).not.toHaveProperty(forbidden)
    expect(screen.queryByRole('region', { name: 'Груз' })).not.toBeInTheDocument()
  })

  it('вкладка «Финансы»: базовая строка заблокирована (нет изменить/удалить), у обычной есть', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: LINES }],
      ...common,
    ])
    renderApp('/orders/5?tab=finance')
    const base = (await screen.findByText('Начальная ставка')).closest('tr')!
    expect(within(base).getByText('Заблокирована')).toBeInTheDocument()
    expect(within(base).queryByRole('button')).not.toBeInTheDocument()
    const normal = screen.getByText('Фрахт').closest('tr')!
    expect(within(normal).getByRole('button', { name: 'Изменить строку: Фрахт' })).toBeEnabled()
    expect(within(normal).getByRole('button', { name: 'Удалить строку: Фрахт' })).toBeEnabled()
    expect(screen.getByText(/ведётся автоматически/)).toBeInTheDocument()
    expect(screen.getByText('Маржа').nextSibling).toHaveTextContent('60,00 %')
  })

  it('финансы: вкладка скрыта без finance.view', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder() }], ...common], {
      session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.view') },
    })
    renderApp('/orders/5?tab=finance')
    await screen.findByRole('heading', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('tab', { name: 'Финансы' })).not.toBeInTheDocument()
    // адрес с tab=finance не открывает скрытую вкладку
    expect(screen.getByRole('tab', { name: 'Обзор' })).toHaveAttribute('aria-selected', 'true')
  })

  it('финансы: кнопки записи скрыты без finance.create/update/delete', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: LINES }],
      ...common,
    ], { session: { permissions: ALL_PERMISSIONS.filter((p) => !['finance.create', 'finance.delete'].includes(p)) } })
    renderApp('/orders/5?tab=finance')
    await screen.findByText('Фрахт')
    expect(screen.queryByRole('button', { name: 'Добавить строку' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Удалить строку/ })).not.toBeInTheDocument()
  })

  it('строку можно отметить как оплату перевозчику по рейсу заказа: уходит trip, в списке бейдж рейса', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: page([makeLine({ id: 200, title: 'Оплата ИП', is_base: false, income: '0.00', expense: '180000.00', trip: 90, trip_number: 'ORD-2026-00005-1' })]) }],
      ['GET', /^\/api\/trips\/\?/, { body: page([{ id: 90, number: 'ORD-2026-00005-1', carrier_name: null, status_name: 'Планируется', is_consolidated: false, vehicle_plate: '', driver_name: '', orders: [{ id: 5, number: 'ORD-2026-00005' }] }]) }],
      ['POST', '/api/order-lines/', { status: 201, body: makeLine({ id: 201 }) }],
      ...common,
    ])
    renderApp('/orders/5?tab=finance')
    expect(await screen.findByText('Рейс ORD-2026-00005-1')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить строку' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Оплата перевозчику')
    await userEvent.clear(within(drawer).getByLabelText('Расход'))
    await userEvent.type(within(drawer).getByLabelText('Расход'), '180000')
    await userEvent.selectOptions(await within(drawer).findByLabelText('Рейс (оплата перевозчику)'), '90')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST' && c.path === '/api/order-lines/')?.body).toMatchObject({ order: 5, expense: '180000', trip: 90 }) })
  })

  it('добавление строки: POST /order-lines/, ошибка поля income ложится на поле', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: LINES }],
      ['POST', '/api/order-lines/', { status: 400, body: { income: ['Не меньше 0'] } }],
      ...common,
    ])
    renderApp('/orders/5?tab=finance')
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить строку' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Страховка')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    const income = await within(drawer).findByLabelText('Доход')
    await waitFor(() => { expect(income).toHaveAttribute('aria-invalid', 'true') })
    expect(within(drawer).getByText('Не меньше 0')).toBeInTheDocument()
    expect(m.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ order: 5, title: 'Страховка', income: '0', expense: '0' })
  })

  it('удаление строки с подтверждением', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: LINES }],
      ['DELETE', '/api/order-lines/101/', { status: 204 }],
      ...common,
    ])
    renderApp('/orders/5?tab=finance')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить строку: Фрахт' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE')).toBe(true) })
  })

  it('вкладка «Грузы»: список с точками; удаление и правка идут в /consignments/', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['DELETE', '/api/consignments/31/', { status: 204 }],
      ['PATCH', '/api/consignments/31/', { status: 400, body: { points: [{}, { city: ['Нужен город'] }] } }],
      ...common,
    ])
    renderApp('/orders/5?tab=cargo')
    expect(await screen.findByText('Станки')).toBeInTheDocument()
    expect(within(screen.getByRole('tabpanel')).getByText(/Алматы/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Изменить груз: Станки' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    const unload = within(await within(drawer).findByRole('region', { name: 'Выгрузка' }))
    await waitFor(() => { expect(unload.getByLabelText(/Город/)).toHaveAttribute('aria-invalid', 'true') })
    expect(unload.getByText('Нужен город')).toBeInTheDocument()
    expect((m.calls.find((c) => c.method === 'PATCH')!.body as { points: { kind: string }[] }).points.map((p) => p.kind)).toEqual(['load', 'unload'])
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Удалить груз: Станки' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE' && c.path === '/api/consignments/31/')).toBe(true) })
  })

  it('вкладка «История»', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder({ history: [
        { id: 1, from_status: null, from_status_name: null, to_status: 1, to_status_name: 'Новый', user: 1, created_at: '2026-10-30T05:00:00Z' },
        { id: 2, from_status: 1, from_status_name: 'Новый', to_status: 2, to_status_name: 'В работе', user: 1, created_at: '2026-10-31T05:00:00Z' },
      ] }) }],
      ...common,
    ])
    renderApp('/orders/5?tab=history')
    const rows = await screen.findAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(within(rows[2]!).getByText('В работе')).toBeInTheDocument()
    expect(within(rows[2]!).getByText('31.10.2026, 10:00')).toBeInTheDocument()
  })

  it('вкладка «Рейсы»: один запрос ?order=<id>, рейсы показываются как есть', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/trips\/\?/, { body: page([
        { id: 1, number: 'ORD-2026-00005-1', carrier_name: 'ТОО Перевоз', status_name: 'В пути', is_consolidated: false, vehicle_plate: '', driver_name: '', orders: [{ id: 5, number: 'ORD-2026-00005' }] },
        { id: 2, number: 'C00001', carrier_name: 'ИП Быстров', status_name: 'Планируется', is_consolidated: true, vehicle_plate: 'A1', driver_name: '', orders: [{ id: 5, number: 'ORD-2026-00005' }, { id: 9, number: 'X' }] },
      ]) }],
      ...common,
    ])
    renderApp('/orders/5?tab=trips')
    expect(await screen.findByRole('link', { name: 'ORD-2026-00005-1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'C00001' })).toBeInTheDocument()
    const trips = m.calls.filter((c) => c.path.startsWith('/api/trips/'))
    expect(trips).toHaveLength(1)
    expect(new URL(trips[0]!.path, 'http://x').searchParams.get('order')).toBe('5')
    expect(trips[0]!.path).not.toContain('only_consolidated')
  })

  it('удаление заказа: подтверждение, DELETE и переход к списку', async () => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['DELETE', '/api/orders/5/', { status: 204 }],
      ['GET', /^\/api\/orders\/\?/, { body: page([]) }],
      ...common,
    ])
    const { router } = renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить заказ' }))
    expect(m.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить заказ' }))
    await waitFor(() => { expect(router.state.location.pathname).toBe('/orders') })
  })

  it('без orders.delete кнопки удаления нет; чужой/несуществующий заказ - «не найден»', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder() }], ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'orders.delete') } })
    renderApp('/orders/5')
    await screen.findByRole('heading', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('button', { name: 'Удалить заказ' })).not.toBeInTheDocument()
  })

  it('404 заказа', async () => {
    loggedIn([['GET', '/api/orders/99/', { status: 404, body: { detail: 'Not found.' } }], ...common])
    renderApp('/orders/99')
    expect(await screen.findByText('Заказ не найден')).toBeInTheDocument()
  })

  it('режим только чтения отключает запись в карточке', async () => {
    loggedIn([['GET', '/api/orders/5/', { body: makeOrder() }], ...common], {
      session: { subscription: { status: 'readonly', plan_code: 'x', days_left: 0, grace_days_left: null, is_free_period: false } },
    })
    renderApp('/orders/5')
    expect(await screen.findByRole('button', { name: 'Изменить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить заказ' })).toBeDisabled()
    expect(screen.queryByRole('combobox', { name: /Статус заказа/ })).not.toBeInTheDocument()
  })

  it('строки заказа: подгружаются все страницы (205 строк)', async () => {
    const mk = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => makeLine({ id: 1000 + from + i, title: `Строка ${String(from + i)}`, is_base: false }))
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder() }],
      ['GET', /^\/api\/order-lines\/\?.*page=2/, { body: { count: 205, next: null, previous: 'x', results: mk(201, 205) } }],
      ['GET', /^\/api\/order-lines\/\?/, { body: { count: 205, next: 'http://x/?page=2', previous: null, results: mk(1, 200) } }],
      ...common,
    ])
    renderApp('/orders/5?tab=finance')
    expect(await screen.findByText('Строка 205')).toBeInTheDocument()
    expect(screen.getByText('Строка 1')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.path.startsWith('/api/order-lines/'))).toHaveLength(2)
  })
})
