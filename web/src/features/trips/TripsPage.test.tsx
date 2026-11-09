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

  it('выход из «Завершён»: диалог причины, без причины не отправляется, с причиной POST status+reason', async () => {
    const done = makeTrip({ status: 23, status_name: 'Завершён', completed_at: '2026-11-05T10:00:00Z' })
    const m = loggedIn([
      ['POST', '/api/trips/90/status/', { body: makeTrip({ status: 22, status_name: 'В пути' }) }],
      ...base([done]),
    ])
    renderApp('/trips')
    const select = await screen.findByRole('combobox', { name: 'Статус рейса ORD-2026-00005-1' })
    await within(select).findByRole('option', { name: 'В пути' })
    await userEvent.selectOptions(select, '22')
    const dialog = await screen.findByRole('dialog', { name: 'Выход из статуса «Завершён»' })
    expect(m.count('POST', '/api/trips/90/status/')).toBe(0) // до ввода причины ничего не уходит
    await userEvent.click(within(dialog).getByRole('button', { name: 'Перевести' }))
    expect(await within(dialog).findByText('Укажите причину')).toBeInTheDocument()
    expect(m.count('POST', '/api/trips/90/status/')).toBe(0)
    await userEvent.type(within(dialog).getByLabelText(/^Причина/), 'Закрыт по ошибке')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Перевести' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.path === '/api/trips/90/status/')?.body).toEqual({ status: 22, reason: 'Закрыт по ошибке' })
    })
  })

  it('без trips.revert_completed опции выхода из «Завершён» отключены', async () => {
    const done = makeTrip({ status: 23, status_name: 'Завершён' })
    loggedIn(base([done]), { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trips.revert_completed') } })
    renderApp('/trips')
    const select = await screen.findByRole('combobox', { name: 'Статус рейса ORD-2026-00005-1' })
    expect(await within(select).findByRole('option', { name: 'В пути' })).toBeDisabled()
    expect(within(select).getByRole('option', { name: 'Планируется' })).toBeDisabled()
    expect(within(select).getByRole('option', { name: 'Завершён' })).toBeEnabled()
    expect(select).toHaveAttribute('title', expect.stringContaining('Рейсы: выводить рейс'))
  })

  it('обычный переход из незавершённого статуса не запрашивает причину', async () => {
    const m = loggedIn([['POST', '/api/trips/90/status/', { body: makeTrip({ status: 23, status_name: 'Завершён' }) }], ...base()])
    renderApp('/trips')
    const select = await screen.findByRole('combobox', { name: 'Статус рейса ORD-2026-00005-1' })
    await within(select).findByRole('option', { name: 'Завершён' })
    await userEvent.selectOptions(select, '23')
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/trips/90/status/')?.body).toEqual({ status: 23 }) })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
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
    expect(Object.keys(body).sort()).toEqual(['carrier', 'carrier_price', 'currency', 'driver_name', 'vehicle_plate'])
    for (const forbidden of ['consignments', 'status', 'number', 'is_consolidated']) expect(body).not.toHaveProperty(forbidden)
    expect(body).toMatchObject({ driver_name: 'Пётр', carrier: 6, carrier_price: '100000.00' })
    expect(body).not.toHaveProperty('price') // устаревший алиас не отправляем
  })

  it('поле «Стоимость перевозчика» берёт carrier_price, а не устаревший price', async () => {
    const priced = makeTrip({ carrier_price: '250000.00', price: '1.00' })
    loggedIn([['GET', '/api/trips/90/', { body: priced }], ...base([priced])])
    renderApp('/trips')
    const row = (await screen.findByRole('button', { name: 'ORD-2026-00005-1' })).closest('tr')!
    expect(within(row).getByText(/^250\s000,00\sKZT$/)).toBeInTheDocument()
    await userEvent.click(within(row).getByRole('button', { name: 'ORD-2026-00005-1' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByLabelText('Стоимость перевозчика')).toHaveValue('250000.00')
  })

  it('в карточке показано время завершения', async () => {
    const done = makeTrip({ status: 23, status_name: 'Завершён', completed_at: '2026-11-05T10:00:00Z' })
    loggedIn([['GET', '/api/trips/90/', { body: done }], ...base([done])])
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: 'ORD-2026-00005-1' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/Завершён: .*2026/)).toBeInTheDocument()
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

describe('Рейсы: следующий шаг одной кнопкой', () => {
  it('«→ В пути» открывает ввод пробега (необязательно) и отправляет статус вместе с пробегом', async () => {
    const m = loggedIn([...base(), ['POST', '/api/trips/90/status/', { body: makeTrip({ status: 22, status_name: 'В пути' }) }]])
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: '→ В пути' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Пробег тягача, км'), '120500')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Продолжить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/trips/90/status/')?.body).toEqual({ status: 22, vehicle_km: 120500 }) })
  })

  it('пробег можно пропустить: уходит только статус', async () => {
    const m = loggedIn([...base(), ['POST', '/api/trips/90/status/', { body: makeTrip({ status: 22, status_name: 'В пути' }) }]])
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: '→ В пути' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Продолжить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/trips/90/status/')?.body).toEqual({ status: 22 }) })
  })

  it('на последнем шаге («Завершён») кнопки следующего шага нет', async () => {
    loggedIn(base([makeTrip({ status: 23, status_name: 'Завершён' })]))
    renderApp('/trips')
    await screen.findByRole('combobox', { name: 'Статус рейса ORD-2026-00005-1' })
    expect(screen.queryByRole('button', { name: /^→/ })).not.toBeInTheDocument()
  })
})
