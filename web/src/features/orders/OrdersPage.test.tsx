import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { BOARD, CURRENCIES, ORDER_STATUSES, handbookBody, makeOrder } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const common = [
  ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
] as MockRoutes

const ordersRoute = (orders = [makeOrder()]): MockRoutes[number] => ['GET', /^\/api\/orders\/\?/, { body: page(orders) }]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Заказы: список', () => {
  it('рисует колонки, ставку с валютой, «Без перевозчика» и финансы', async () => {
    loggedIn([ordersRoute(), ...common])
    renderApp('/orders')
    const link = await screen.findByRole('link', { name: 'ORD-2026-00005' })
    expect(link).toHaveAttribute('href', '/orders/5')
    const row = link.closest('tr')!
    expect(within(row).getByText('ТОО Ромашка')).toBeInTheDocument()
    expect(within(row).getByText('Алматы → Астана')).toBeInTheDocument()
    expect(within(row).getByText('Без перевозчика')).toBeInTheDocument()
    expect(within(row).getByText(/^250\s000,00\sKZT$/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Расходы' })).toBeInTheDocument()
    expect(within(row).getByText(/^150\s000,00$/)).toBeInTheDocument()
  })

  it('без finance.view колонок расходов и прибыли нет', async () => {
    loggedIn([ordersRoute(), ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.view') } })
    renderApp('/orders')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('columnheader', { name: 'Расходы' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Прибыль' })).not.toBeInTheDocument()
  })

  it('отправляет на сервер полный набор фильтров из адреса', async () => {
    const m = loggedIn([
      ordersRoute(),
      ['GET', '/api/clients/5/', { body: { id: 5, name: 'ТОО Ромашка' } }],
      ['GET', '/api/carriers/6/', { body: { id: 6, name: 'ИП Быстров' } }],
      ...common,
    ])
    renderApp(
      '/orders?q=abc&status=1,2&client=5&carrier=6&loading_from=2026-10-01&loading_to=2026-10-31&created_from=2026-09-01&created_to=2026-09-30&completed_from=2026-08-01&completed_to=2026-08-31&unassigned=1&ordering=number&page=2&pageSize=20',
    )
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    const request = m.calls.find((c) => c.path.startsWith('/api/orders/?'))!
    const query = new URL(request.path, 'http://x').searchParams
    expect(Object.fromEntries(query)).toEqual({
      q: 'abc', status: '1,2', client: '5', carrier: '6', loading_from: '2026-10-01', loading_to: '2026-10-31',
      created_from: '2026-09-01', created_to: '2026-09-30', completed_from: '2026-08-01', completed_to: '2026-08-31',
      unassigned: '1', ordering: 'number', page: '2', page_size: '20',
    })
    // подписи выбранных клиента и перевозчика подтягиваются по id
    expect(await screen.findByDisplayValue('ТОО Ромашка')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('ИП Быстров')).toBeInTheDocument()
  })

  it('мусор в адресе не роняет страницу и даёт фильтры по умолчанию', async () => {
    const m = loggedIn([ordersRoute(), ...common])
    renderApp('/orders?page=-1&status=a,b&ordering=;drop&client=x&loading_from=вчера&unassigned=да&view=3d')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    const query = new URL(m.calls.find((c) => c.path.startsWith('/api/orders/?'))!.path, 'http://x').searchParams
    expect(Object.fromEntries(query)).toEqual({ ordering: '-created_at', page: '1', page_size: '50' })
  })

  it('изменение фильтра обновляет адрес и запрос, страница сбрасывается', async () => {
    const m = loggedIn([ordersRoute(), ...common])
    const { router } = renderApp('/orders?page=3')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('checkbox', { name: 'Без перевозчика' })).not.toBeInTheDocument()  // доп. фильтры скрыты
    await userEvent.click(screen.getByRole('button', { name: 'Дополнительные фильтры' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Без перевозчика' }))
    await waitFor(() => { expect(router.state.location.search).toContain('unassigned=1') })
    expect(router.state.location.search).not.toContain('page=')
    await waitFor(() => { expect(m.calls.some((c) => c.path.includes('unassigned=1'))).toBe(true) })
  })

  it('дополнительные фильтры открыты сами, если по ним уже есть выборка, и показывают их число', async () => {
    loggedIn([ordersRoute(), ...common])
    renderApp('/orders?unassigned=1&loading_from=2026-01-01')
    expect(await screen.findByRole('button', { name: 'Дополнительные фильтры (2)' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Без перевозчика' })).toBeChecked()
  })

  it('пустой список без фильтров - состояние с кнопкой «Новый заказ»', async () => {
    loggedIn([ordersRoute([]), ...common])
    renderApp('/orders')
    expect(await screen.findByText('Заказов пока нет')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Новый заказ' }).length).toBeGreaterThan(1)
  })

  it('смена статуса в строке: POST /status/ и обновление списка', async () => {
    let status = 1
    const m = loggedIn([
      ['POST', '/api/orders/5/status/', (call) => { status = (call.body as { status: number }).status; return { body: makeOrder({ status }) } }],
      ['GET', /^\/api\/orders\/\?/, () => ({ body: page([makeOrder({ status, status_name: status === 2 ? 'В работе' : 'Новый' })]) })],
      ...common,
    ])
    renderApp('/orders')
    const select = await screen.findByRole('combobox', { name: 'Статус заказа ORD-2026-00005' })
    await userEvent.selectOptions(select, 'В работе')
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 2 }) })
    await waitFor(() => { expect(m.calls.filter((c) => c.path.startsWith('/api/orders/?')).length).toBeGreaterThan(1) })
    await waitFor(() => { expect(screen.getByRole('combobox', { name: 'Статус заказа ORD-2026-00005' })).toHaveValue('2') })
  })

  it('без orders.update статус - значок, без выпадающего списка', async () => {
    loggedIn([ordersRoute(), ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'orders.update') } })
    renderApp('/orders')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    expect(screen.queryByRole('combobox', { name: /Статус заказа/ })).not.toBeInTheDocument()
  })
})

describe('Заказы: канбан', () => {
  it('показывает все колонки, в т.ч. пустые, счётчики, пометку «показаны не все» и «Без перевозчика»', async () => {
    const m = loggedIn([['GET', /^\/api\/orders\/board\//, { body: BOARD }], ...common])
    renderApp('/orders?view=board&client=5&unassigned=1')
    const columns = await screen.findAllByRole('region')
    expect(columns.map((c) => c.getAttribute('aria-label'))).toEqual(['Новый', 'В работе', 'Завершён'])
    const first = within(screen.getByRole('region', { name: 'Новый' }))
    expect(first.getByText('120')).toBeInTheDocument()
    expect(first.getByText('Показано 2 из 120. Уточните фильтры, чтобы увидеть остальные.')).toBeInTheDocument()
    expect(first.getByText('Без перевозчика')).toBeInTheDocument()
    expect(first.getByText('ИП Быстров')).toBeInTheDocument()
    expect(first.getByRole('link', { name: 'ORD-2026-00005' })).toHaveAttribute('href', '/orders/5')
    expect(within(screen.getByRole('region', { name: 'В работе' })).getByText('Нет заказов')).toBeInTheDocument()
    expect(m.calls.find((c) => c.path.startsWith('/api/orders/board/'))!.path).toContain('client=5')
    expect(m.calls.find((c) => c.path.startsWith('/api/orders/board/'))!.path).toContain('unassigned=1')
  })

  it('смена статуса из карточки', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/orders\/board\//, { body: BOARD }],
      ['POST', '/api/orders/6/status/', { body: makeOrder({ id: 6 }) }],
      ...common,
    ])
    renderApp('/orders?view=board')
    const select = await screen.findByRole('combobox', { name: 'Статус заказа ORD-2026-00006' })
    await userEvent.selectOptions(select, 'Завершён')
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 6 }) })
  })

  it('переключатель вида пишет view в адрес', async () => {
    loggedIn([ordersRoute(), ['GET', /^\/api\/orders\/board\//, { body: BOARD }], ...common])
    const { router } = renderApp('/orders')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    await userEvent.click(screen.getByRole('button', { name: 'Канбан' }))
    await waitFor(() => { expect(router.state.location.search).toContain('view=board') })
  })
})

describe('Заказы: Excel', () => {
  it('скачивает blob через клиент с заголовком авторизации и фильтрами; имя очищено, ссылка отозвана', async () => {
    const created: Blob[] = []
    const revoke = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => { created.push(b); return 'blob:x' }, revokeObjectURL: revoke }))
    const names: string[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download) })
    const m = loggedIn([
      ordersRoute(),
      ['GET', /^\/api\/orders\/export\//, { headers: { 'Content-Disposition': 'attachment; filename="../../evil.exe"' } }],
      ...common,
    ])
    renderApp('/orders?q=abc&status=1')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    await userEvent.click(screen.getByRole('button', { name: 'Excel' }))
    await waitFor(() => { expect(click).toHaveBeenCalled() })
    const call = m.calls.find((c) => c.path.startsWith('/api/orders/export/'))!
    expect(call.path).toContain('q=abc')
    expect(call.path).toContain('status=1')
    expect(call.headers.Authorization).toBe('Bearer a')
    expect(created).toHaveLength(1)
    expect(names).toEqual(['evil.exe'])
    expect(revoke).toHaveBeenCalledWith('blob:x')
    click.mockRestore()
  })

  it('400 о лимите строк показывается сообщением', async () => {
    loggedIn([
      ordersRoute(),
      ['GET', /^\/api\/orders\/export\//, { status: 400, body: ['Слишком много заказов для выгрузки (больше 10 000): сузьте фильтр'] }],
      ...common,
    ])
    renderApp('/orders')
    await screen.findByRole('link', { name: 'ORD-2026-00005' })
    await userEvent.click(screen.getByRole('button', { name: 'Excel' }))
    expect(await screen.findByText(/Слишком много заказов для выгрузки/)).toBeInTheDocument()
  })

  it('страница за последней (404) возвращает на первую, а не показывает ошибку', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/orders\/\?.*page=9/, { status: 404, body: { detail: 'Неверная страница.' } }],
      ordersRoute(),
      ...common,
    ])
    const { router } = renderApp('/orders?page=9')
    expect(await screen.findByRole('link', { name: 'ORD-2026-00005' })).toBeInTheDocument()
    expect(router.state.location.search).not.toContain('page=9')
    expect(m.calls.some((c) => c.path.includes('page=9'))).toBe(true)
  })
})
