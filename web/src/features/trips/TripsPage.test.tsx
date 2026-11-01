import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'
import { TRIP_STATUSES, makeCargo, makeTrip } from '../../test/trips'

const base = (trips = [makeTrip()]): MockRoutes => [
  ['GET', /^\/api\/trips\/\?/, { body: page(trips) }],
  ['GET', '/api/trips/90/', { body: makeTrip() }],
  ['GET', '/api/handbooks/?code=trip_status', { body: handbookBody('trip_status', TRIP_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Рейсы: список', () => {
  it('q и order из адреса уходят в запрос списка', async () => {
    const m = loggedIn(base())
    renderApp('/trips?q=ORD-2026-00005-1&order=5&consolidated=1')
    await screen.findByRole('button', { name: 'ORD-2026-00005-1' })
    const q = new URL(m.calls.find((c) => c.path.startsWith('/api/trips/?'))!.path, 'http://x').searchParams
    expect(Object.fromEntries(q)).toMatchObject({ q: 'ORD-2026-00005-1', order: '5', only_consolidated: '1' })
  })

  it('колонки: перевозчик, машина/водитель, ссылки на заказы, цена с валютой', async () => {
    loggedIn(base())
    renderApp('/trips')
    const row = (await screen.findByRole('button', { name: 'ORD-2026-00005-1' })).closest('tr')!
    expect(within(row).getByText('ИП Быстров')).toBeInTheDocument()
    expect(within(row).getByText('123ABC02 / Иван')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'ORD-2026-00005' })).toHaveAttribute('href', '/orders/5')
    expect(within(row).getByText(/^100\s000,00\sKZT$/)).toBeInTheDocument()
  })

  it('статус меняется на месте: POST /status/', async () => {
    const m = loggedIn([...base(), ['POST', '/api/trips/90/status/', { body: makeTrip({ status: 22, status_name: 'В пути' }) }]])
    renderApp('/trips')
    const select = await screen.findByRole('combobox', { name: 'Статус рейса ORD-2026-00005-1' })
    await within(select).findByRole('option', { name: 'В пути' })
    await userEvent.selectOptions(select, '22')
    await waitFor(() => {
      expect(m.calls.find((c) => c.path === '/api/trips/90/status/')?.body).toEqual({ status: 22 })
    })
  })

  it('без trips.update статус - значок, не список', async () => {
    loggedIn(base(), { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trips.update') } })
    renderApp('/trips')
    const row = (await screen.findByRole('button', { name: 'ORD-2026-00005-1' })).closest('tr')!
    expect(screen.queryByRole('combobox', { name: /Статус рейса/ })).not.toBeInTheDocument()
    expect(within(row).getByText('Планируется')).toBeInTheDocument()
  })
})

describe('Рейс: карточка', () => {
  const open = async (extra: MockRoutes = [], session = {}) => {
    const m = loggedIn([...extra, ...base()], { session })
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: 'ORD-2026-00005-1' }))
    return { m, dialog: await screen.findByRole('dialog') }
  }

  it('PATCH несёт только редактируемые поля', async () => {
    const { m, dialog } = await open([['PATCH', '/api/trips/90/', { body: makeTrip({ driver_name: 'Пётр' }) }]])
    const driver = await within(dialog).findByLabelText('Водитель')
    await userEvent.clear(driver)
    await userEvent.type(driver, 'Пётр')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['carrier', 'currency', 'driver_name', 'price', 'vehicle_plate'])
    for (const forbidden of ['consignments', 'status', 'number', 'is_consolidated']) expect(body).not.toHaveProperty(forbidden)
    expect(body).toMatchObject({ driver_name: 'Пётр', carrier: 6, price: '100000.00' })
  })

  it('«Изменить грузы»: пустой набор не отправляется, иначе POST consignment_ids', async () => {
    const found = makeCargo({ id: 40, name: 'Трубы', order: 6, order_number: 'ORD-6' })
    const { m, dialog } = await open([
      ['GET', /^\/api\/consignments\/\?/, { body: page([makeCargo(), found]) }],
      ['POST', '/api/trips/90/reassign/', { body: makeTrip() }],
    ])
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Изменить грузы' }))
    const reassign = await screen.findByRole('dialog', { name: 'Грузы рейса ORD-2026-00005-1' })
    expect(within(reassign).getByText(/Номер рейса не изменится/)).toBeInTheDocument()
    // убрали единственный груз -> ошибка, запроса нет
    await userEvent.click(within(reassign).getByRole('checkbox', { name: 'Станки (ORD-2026-00005)' }))
    await userEvent.click(within(reassign).getByRole('button', { name: 'Сохранить' }))
    expect(await within(reassign).findByText('В рейсе должен остаться хотя бы один груз')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path.endsWith('/reassign/'))).toBe(false)
    // вернули и добавили найденный
    await userEvent.click(within(reassign).getByRole('checkbox', { name: 'Станки (ORD-2026-00005)' }))
    await userEvent.click(await within(reassign).findByRole('checkbox', { name: 'Трубы (ORD-6)' }))
    await userEvent.click(within(reassign).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/trips/90/reassign/')).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/trips/90/reassign/')!.body).toEqual({ consignment_ids: [31, 40] })
  })

  it('удаление через подтверждение: DELETE и пояснение про очередь', async () => {
    const { m, dialog } = await open([['DELETE', '/api/trips/90/', { status: 204 }]])
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Удалить рейс' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/грузы вернутся в очередь/)).toBeInTheDocument()
    await userEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE' && c.path === '/api/trips/90/')).toBe(true) })
  })

  it('в режиме только чтения правка и удаление отключены', async () => {
    const { dialog } = await open([], { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } })
    expect(await within(dialog).findByRole('button', { name: 'Сохранить' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'Изменить грузы' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'Удалить рейс' })).toBeDisabled()
  })
})
