import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody, makeOrder } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const CLIENT = { id: 7, name: 'ТОО Ромашка', contacts: [{ id: 70, name: 'Иван Петров', position: '', phone: '', email: '' }] }
const USERS = [
  { user_id: 1, full_name: 'Админ Админов', email: 'a@x.kz', phone: null, is_active: true },
  { user_id: 2, full_name: 'Мария Менеджер', email: 'm@x.kz', phone: null, is_active: true },
]

const base = [
  ['GET', /^\/api\/clients\/\?/, { body: page([{ id: 7, name: 'ТОО Ромашка' }]) }],
  ['GET', '/api/clients/7/', { body: CLIENT }],
  ['GET', '/api/users/', { body: USERS }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
] as MockRoutes

async function pickClient() {
  const input = screen.getByRole('combobox', { name: /Клиент/ })
  await userEvent.click(input)
  await userEvent.click(await screen.findByRole('option', { name: 'ТОО Ромашка' }))
}

async function addValidCargo() {
  await userEvent.click(screen.getByRole('button', { name: 'Добавить груз' }))
  const cargo = screen.getByRole('region', { name: 'Груз' })
  await userEvent.type(within(cargo).getByLabelText(/Название груза/), 'Станки')
  await userEvent.type(within(cargo).getByLabelText(/Вес, кг/), '1200')
  await userEvent.type(within(cargo).getByLabelText(/Объём/), '8.5')
  const route = screen.getByRole('region', { name: 'Маршрут' })
  const load = within(within(route).getByRole('region', { name: 'Погрузка' }))
  const unload = within(within(route).getByRole('region', { name: 'Выгрузка' }))
  fireEvent.change(load.getByLabelText(/Окно с/), { target: { value: '2026-11-05T09:00' } })
  await userEvent.type(load.getByLabelText(/Город/), 'Алматы')
  fireEvent.change(unload.getByLabelText(/Окно с/), { target: { value: '2026-11-08T09:00' } })
  return { load, unload }
}

describe('Новый заказ', () => {
  it('четыре блока и менеджер по умолчанию - текущий пользователь', async () => {
    loggedIn(base)
    renderApp('/orders/new')
    for (const name of ['Контакты', 'Ценник', 'Груз', 'Маршрут']) expect(await screen.findByRole('region', { name })).toBeInTheDocument()
    await waitFor(() => { expect(screen.getByLabelText('Менеджер')).toHaveValue('1') })
  })

  it('в выборе клиента для нового заказа только активные (status=active); сервер может отказать неактивному', async () => {
    const m = loggedIn([
      ...base,
      ['POST', '/api/orders/', { status: 400, body: { client: ['Клиент неактивен: новые заказы по нему не создаются. Сделайте клиента активным или выберите другого.'] } }],
    ])
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    const search = m.calls.find((c) => c.path.startsWith('/api/clients/?'))!
    expect(new URL(search.path, 'http://x').searchParams.get('status')).toBe('active')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText(/Клиент неактивен/)).toBeInTheDocument()
  })

  it('без users.view селекторы сотрудников скрыты, запрос /users/ не уходит, manager не отправляется', async () => {
    const m = loggedIn(
      [...base, ['POST', '/api/orders/', { status: 201, body: makeOrder() }], ['GET', '/api/orders/5/', { body: makeOrder() }]],
      { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'users.view') } },
    )
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    expect(screen.queryByLabelText('Менеджер')).not.toBeInTheDocument()
    expect(screen.getByText('Менеджером заказа будете вы.')).toBeInTheDocument()
    await pickClient()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST')).toBe(true) })
    expect(m.calls.some((c) => c.path === '/api/users/')).toBe(false)
    expect(m.calls.find((c) => c.method === 'POST')!.body).not.toHaveProperty('manager')
  })

  it('без клиента отправка блокируется и показывается ошибка', async () => {
    const m = loggedIn(base)
    renderApp('/orders/new')
    await userEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    const client = screen.getByRole('combobox', { name: /Клиент/ })
    await waitFor(() => { expect(client).toHaveAttribute('aria-invalid', 'true') })
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('груз без точек (пустые окно и город) блокирует отправку: ошибки на полях обеих точек', async () => {
    const m = loggedIn(base)
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить груз' }))
    await userEvent.type(screen.getByLabelText(/Название груза/), 'Станки')
    await userEvent.type(screen.getByLabelText(/Вес, кг/), '10')
    await userEvent.type(screen.getByLabelText(/Объём/), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    const route = screen.getByRole('region', { name: 'Маршрут' })
    for (const point of ['Погрузка', 'Выгрузка']) {
      const section = within(within(route).getByRole('region', { name: point }))
      await waitFor(() => { expect(section.getByLabelText(/Город/)).toHaveAttribute('aria-invalid', 'true') })
      expect(section.getByLabelText(/Окно с/)).toHaveAttribute('aria-invalid', 'true')
    }
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('успех: тело содержит груз с двумя точками (погрузка, выгрузка) и ведёт на заказ', async () => {
    const m = loggedIn([
      ...base,
      ['POST', '/api/orders/', { status: 201, body: makeOrder() }],
      ['GET', '/api/orders/5/', { body: makeOrder() }],
    ])
    const { router } = renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    const { unload } = await addValidCargo()
    await userEvent.type(unload.getByLabelText(/Город/), 'Астана')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(router.state.location.pathname).toBe('/orders/5') })
    const body = m.calls.find((c) => c.method === 'POST')!.body as { client: number; manager: number; consignments: { points: { kind: string; city: string; window_from: string }[] }[] }
    expect(body.client).toBe(7)
    expect(body.manager).toBe(1)
    expect(body.consignments[0]!.points.map((p) => [p.kind, p.city, p.window_from])).toEqual([
      ['load', 'Алматы', '2026-11-05T04:00:00.000Z'],
      ['unload', 'Астана', '2026-11-08T04:00:00.000Z'],
    ])
  })

  it('вложенная ошибка сервера consignments.0.points.1.city ложится на поле «Город» выгрузки', async () => {
    loggedIn([
      ...base,
      ['POST', '/api/orders/', { status: 400, body: { consignments: [{ points: [{}, { city: ['Укажите город (сервер)'] }] }] } }],
    ])
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    const { load, unload } = await addValidCargo()
    await userEvent.type(unload.getByLabelText(/Город/), 'Астана')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    const city = await unload.findByLabelText(/Город/)
    await waitFor(() => { expect(city).toHaveAttribute('aria-invalid', 'true') })
    expect(unload.getByText('Укажите город (сервер)')).toBeInTheDocument()
    expect(load.getByLabelText(/Город/)).not.toHaveAttribute('aria-invalid')
  })

  it('ошибки уровня формы и неизвестных полей идут в баннер; 409 локализован', async () => {
    loggedIn([
      ...base,
      ['POST', '/api/orders/', { status: 400, body: { non_field_errors: ['Что-то общее'], legal_entity: ['Укажите юрлицо'] } }],
    ])
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Что-то общее')
    expect(alert).toHaveTextContent('legal_entity: Укажите юрлицо')
  })

  it('лимит тарифа показывается понятным сообщением', async () => {
    loggedIn([...base, ['POST', '/api/orders/', { status: 403, body: { detail: 'limit', code: 'limit_exceeded' } }]])
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await pickClient()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Достигнут лимит тарифа')).toBeInTheDocument()
  })

  it('контакт выбирается из контактов клиента', async () => {
    loggedIn(base)
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    // необязательные поля свёрнуты в «Дополнительно» и раскрываются по кнопке
    expect(screen.queryByLabelText('Контакт клиента')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Номер договора')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Дополнительно/ }))
    expect(screen.getByLabelText('Контакт клиента')).toBeDisabled()
    await pickClient()
    const contact = screen.getByLabelText('Контакт клиента')
    await waitFor(() => { expect(within(contact).getByRole('option', { name: 'Иван Петров' })).toBeInTheDocument() })
  })

  it('маршрут: простой режим - дата, город, адрес; подробности и остановки раскрываются по кнопке', async () => {
    loggedIn(base)
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить груз' }))
    const load = await screen.findByRole('region', { name: 'Погрузка' })
    expect(within(load).getByLabelText(/Город/)).toBeInTheDocument()
    expect(within(load).queryByLabelText('Страна')).not.toBeInTheDocument()
    await userEvent.click(within(load).getByRole('button', { name: /Подробнее/ }))
    expect(within(load).getByLabelText('Страна')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Несколько остановок' })[0]!)
    expect(await screen.findByRole('region', { name: 'Остановка 1' })).toBeInTheDocument()
  })

  it('без orders.create - страница 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'orders.create') } })
    renderApp('/orders/new')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
