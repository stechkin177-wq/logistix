import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'
import { makeCargo, makeTrip } from '../../test/trips'

const two = [
  makeCargo({ id: 31, name: 'Станки', order: 5, order_number: 'ORD-5' }),
  makeCargo({ id: 32, name: 'Ящики', order: 6, order_number: 'ORD-6', client_name: 'ИП Лютик', trips_count: 2 }),
]
const base = (rows = two): MockRoutes => [
  ['GET', /^\/api\/consignments\/\?/, { body: page(rows) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Грузы', () => {
  it('рисует колонки: маршрут, заказ, клиент, «без рейса» и число рейсов', async () => {
    loggedIn(base())
    renderApp('/consignments')
    const row = (await screen.findByText('Станки')).closest('tr')!
    expect(within(row).getByText('Алматы → Астана')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'ORD-5' })).toHaveAttribute('href', '/orders/5')
    expect(within(row).getByText('ТОО Ромашка')).toBeInTheDocument()
    expect(within(row).getByText('без рейса')).toBeInTheDocument()
    expect(within(screen.getByText('Ящики').closest('tr')!).getByText('2')).toBeInTheDocument()
  })

  it('переключатель очереди и клиент уходят в запрос как without_trip=1 и client', async () => {
    const m = loggedIn(base())
    renderApp('/consignments?client=7')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Очередь на распределение' }))
    await waitFor(() => {
      const last = m.calls.filter((c) => c.path.startsWith('/api/consignments/?')).at(-1)!
      const q = new URL(last.path, 'http://x').searchParams
      expect(q.get('without_trip')).toBe('1')
      expect(q.get('client')).toBe('7')
    })
  })

  it('грузы двух заказов: уведомление о сборном рейсе и POST с нужными id', async () => {
    const m = loggedIn([
      ...base(),
      ['POST', '/api/trips/', { status: 201, body: makeTrip({ id: 91, number: 'C1', is_consolidated: true }) }],
    ])
    renderApp('/consignments')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все на странице' }))
    await userEvent.click(screen.getByRole('button', { name: 'Создать рейс' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Сборный рейс \(консолидация\)/)).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Госномер'), '777AAA02')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/trips/')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'POST' && c.path === '/api/trips/')!.body as Record<string, unknown>
    expect(body).toMatchObject({ consignments: [31, 32], vehicle_plate: '777AAA02', carrier_price: '0', currency: 11, carrier: null })
    // успех: номер нового рейса и ссылка в уведомлении
    expect(await screen.findByText(/Рейс C1 создан/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Открыть' })).toHaveAttribute('href', '/trips?q=C1')
  })

  it('грузы одного заказа: уведомления о сборном рейсе нет', async () => {
    loggedIn(base([makeCargo()]))
    renderApp('/consignments')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать груз Станки' }))
    await userEvent.click(screen.getByRole('button', { name: 'Создать рейс' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByText(/Сборный рейс/)).not.toBeInTheDocument()
  })

  it('ошибка поля сервера ложится на поле, номер занят и чужие id показываются', async () => {
    let reply: { status: number; body: unknown } = { status: 400, body: { carrier_price: ['Цена не может быть отрицательной'] } }
    loggedIn([...base([makeCargo()]), ['POST', '/api/trips/', () => reply]])
    renderApp('/consignments')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать груз Станки' }))
    await userEvent.click(screen.getByRole('button', { name: 'Создать рейс' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    expect(await within(dialog).findByText('Цена не может быть отрицательной')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Стоимость перевозчика')).toHaveAttribute('aria-invalid', 'true')

    reply = { status: 409, body: { detail: 'Номер рейса уже занят', code: 'number_conflict' } }
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    expect(await within(dialog).findByText(/Номер уже занят/)).toBeInTheDocument()

    reply = { status: 400, body: { consignments: ['Грузы не найдены или удалены: 31'] } }
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    expect(await within(dialog).findByText('Грузы не найдены или удалены: 31')).toBeInTheDocument()
  })

  it('без trips.create и в режиме только чтения «Создать рейс» отключена', async () => {
    loggedIn(base(), { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trips.create') } })
    renderApp('/consignments')
    await screen.findByText('Станки')
    expect(screen.getByRole('button', { name: 'Создать рейс' })).toBeDisabled()
  })

  it('в режиме только чтения «Создать рейс» отключена', async () => {
    loggedIn(base(), { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/consignments')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать груз Станки' }))
    expect(screen.getByRole('button', { name: 'Создать рейс' })).toBeDisabled()
  })

  it('прямой заход без права consignments.view даёт 403', async () => {
    loggedIn(base(), { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'consignments.view') } })
    renderApp('/consignments')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
