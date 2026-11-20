import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const SESSION = { modules: ['logistics', 'drivers', 'driver_app'], permissions: ['driver.use'], role: { id: 7, name: 'Водитель' } }
const TRIP = {
  id: 4, number: 'ORD-1-1', status: { id: 3, code: 'ASSIGNED', name: 'Ожидает выезда' }, vehicle_plate: '886AIA14', trailer_plate: '123TT01',
  from_city: 'Алматы', to_city: 'Москва', starts_at: '2026-11-21T04:00:00Z', actions: ['start'], odometer_required: true,
  current_odometer_km: 104000, engine_hours_required: true, current_engine_hours: 10.5, reefer_plate: '123TT01',
}
const DETAIL = {
  ...TRIP,
  stops: [
    { id: 1, kind: 'load', status: 'planned', city: 'Алматы', street: 'ул. Складская 1', contact: '+77001112233', note: '', window_from: '2026-11-21T04:00:00Z', window_to: null, consignment: 'Груз' },
    { id: 2, kind: 'unload', status: 'planned', city: 'Москва', street: '', contact: '', note: 'вход со двора', window_from: '2026-11-25T04:00:00Z', window_to: null, consignment: 'Груз' },
  ],
  consignments: [{ name: 'Запчасти', weight_kg: '1200.00' }],
}

describe('Приложение водителя', () => {
  it('водитель с офисного адреса попадает в свою оболочку и видит рейсы', async () => {
    loggedIn([['GET', /^\/api\/driver\/trips\//, { body: { results: [TRIP] } }]], { session: SESSION })
    renderApp('/?scope=upcoming')
    expect(await screen.findByText('ORD-1-1')).toBeInTheDocument()
    expect(screen.getByText('Алматы → Москва')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Разделы приложения водителя' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Заказы' })).not.toBeInTheDocument() // офисного меню нет
  })

  it('пустой список: понятная подсказка', async () => {
    loggedIn([['GET', /^\/api\/driver\/trips\//, { body: { results: [] } }]], { session: SESSION })
    renderApp('/driver')
    expect(await screen.findByText('Сейчас вы не в рейсе')).toBeInTheDocument()
  })

  it('выезд: ничего вводить не нужно, показан пробег из прошлого рейса; завершение: пробег и моточасы обязательны', async () => {
    const m = loggedIn(
      [
        ['GET', '/api/driver/trips/4/', { body: DETAIL }],
        ['POST', '/api/driver/trips/4/action/', { body: { ...DETAIL, status: { id: 4, code: 'IN_PROGRESS', name: 'В пути' }, actions: ['unloading', 'complete'] } }],
        ['GET', /^\/api\/driver\/trips\/\?/, { body: { results: [] } }],
      ],
      { session: SESSION },
    )
    renderApp('/driver/trips/4')
    expect(await screen.findByText('ул. Складская 1')).toBeInTheDocument()
    expect(screen.getByText('вход со двора')).toBeInTheDocument()
    expect(screen.getByText(/Запчасти · 1200.00 кг/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Выехал' }))
    let dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Пробег машины сейчас: 104000 км/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Моточасы установки сейчас: 10.5/)).toBeInTheDocument()
    expect(within(dialog).queryByLabelText(/Пробег/)).not.toBeInTheDocument() // вводить нечего
    await userEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ action: 'start' })
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    await userEvent.click(await screen.findByRole('button', { name: 'Завершил рейс' }))
    dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: 'Подтвердить' })
    expect(confirm).toBeDisabled() // пробег и моточасы обязательны
    await userEvent.type(within(dialog).getByLabelText(/Пробег машины, км/), '104900')
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Моточасы установки \(123TT01\)/), '14,5')
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(2) })
    expect(m.calls.filter((c) => c.method === 'POST')[1]?.body).toEqual({ action: 'complete', vehicle_km: 104900, engine_hours: 14.5 })
  })

  it('профиль: данные карточки водителя и выход', async () => {
    loggedIn(
      [['GET', '/api/driver/me/', { body: { driver: { id: 1, full_name: 'Иванов Иван', phone: '+77001112233', license_number: 'KZ-1', license_categories: 'C,E', license_expires: '2027-01-01' }, company: { id: 10, name: 'Альфа', language: 'ru' } } }]],
      { session: SESSION },
    )
    renderApp('/driver/profile')
    expect(await screen.findByRole('heading', { name: 'Иванов Иван' })).toBeInTheDocument()
    expect(screen.getByText('+77001112233')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Выйти' })).toBeInTheDocument()
  })

  it('пользователь без права driver.use из области /driver уходит на главную', async () => {
    loggedIn([['GET', /^\/api\/dashboard\//, { body: {} }]], { session: { permissions: ['orders.view'], modules: ['logistics'] } })
    renderApp('/driver')
    await waitFor(() => { expect(screen.queryByRole('navigation', { name: 'Разделы приложения водителя' })).not.toBeInTheDocument() })
  })

  it('офис: доступ в приложение выдаётся паролем и отзывается', async () => {
    const DRIVER = {
      id: 5, full_name: 'Сериков Ерлан', phone: '+77001112233', iin: '', birth_date: null, license_number: '', license_categories: '', license_expires: null,
      status: 'active', user: null, notes: '', documents: [], created_at: '2026-10-01T05:00:00Z', updated_at: '2026-10-01T05:00:00Z',
    }
    const m = loggedIn(
      [
        ['GET', /^\/api\/drivers\/\?/, { body: page([DRIVER]) }],
        ['POST', '/api/drivers/5/grant-access/', { status: 201, body: { user: 9, login: '+77001112233' } }],
        ['POST', '/api/drivers/5/revoke-access/', { body: { revoked: true } }],
      ],
      { session: { modules: ['logistics', 'drivers', 'documents', 'driver_app'] } },
    )
    renderApp('/drivers')
    await userEvent.click(await screen.findByText('Сериков Ерлан'))
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText('Пароль для водителя'), 'Drv-pass-2026!x')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Дать доступ' }))
    expect(await within(drawer).findByText('Доступ выдан: вход по телефону +77001112233')).toBeInTheDocument()
    expect(m.calls.find((c) => c.path === '/api/drivers/5/grant-access/')?.body).toEqual({ password: 'Drv-pass-2026!x' })
    await userEvent.click(within(drawer).getByRole('button', { name: 'Отозвать доступ' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/drivers/5/revoke-access/')).toBe(true) })
    expect(await within(drawer).findByRole('button', { name: 'Дать доступ' })).toBeInTheDocument()
  })
})
