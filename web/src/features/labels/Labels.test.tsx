import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody, makeOrder } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const RED = { id: 1, name: 'Срочно', color: 'red', usage_count: 2, created_at: '2026-11-01T00:00:00Z' }
const BLUE = { id: 2, name: 'VIP', color: 'blue', usage_count: 0, created_at: '2026-11-01T00:00:00Z' }

describe('Страница меток', () => {
  it('список с числом объектов; создание шлёт POST с цветом', async () => {
    const m = loggedIn([
      ['GET', '/api/labels/', { body: [RED, BLUE] }],
      ['POST', '/api/labels/', { status: 201, body: { ...BLUE, id: 3, name: 'Новая', color: 'green' } }],
    ])
    renderApp('/settings/labels')
    expect(await screen.findByRole('heading', { name: 'Метки' })).toBeInTheDocument()
    expect(await screen.findByText('Срочно')).toBeInTheDocument()
    expect(screen.getByText('объектов: 2')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Создать' })[0]!)
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Название/), 'Новая')
    await userEvent.selectOptions(within(dialog).getByLabelText('Цвет'), 'green')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/labels/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')!.body).toEqual({ name: 'Новая', color: 'green' })
  })

  it('удаление: подтверждение с числом объектов и DELETE', async () => {
    const m = loggedIn([['GET', '/api/labels/', { body: [RED] }], ['DELETE', '/api/labels/1/', { status: 204 }]])
    renderApp('/settings/labels')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить метку Срочно' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/снята со всех объектов \(сейчас: 2\)/)).toBeInTheDocument()
    await userEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE' && c.path === '/api/labels/1/')).toBe(true) })
  })

  it('без labels.manage страница недоступна', async () => {
    loggedIn([['GET', '/api/labels/', { body: [] }]], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'labels.manage') } })
    renderApp('/settings/labels')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(screen.queryByRole('heading', { name: 'Метки' })).not.toBeInTheDocument()
  })
})

const orderRoutes = (labels: unknown[]): MockRoutes => [
  ['GET', '/api/orders/5/', { body: { ...makeOrder(), labels } }],
  ['GET', '/api/labels/', { body: [RED, BLUE] }],
  ['GET', /^\/api\/handbooks\/\?code=currency/, { body: handbookBody('currency', CURRENCIES) }],
]

describe('Метки на карточке заказа', () => {
  it('чипы в шапке; выбор меток в окне шлёт PUT со списком id', async () => {
    const m = loggedIn([...orderRoutes([{ id: 1, name: 'Срочно', color: 'red' }]), ['PUT', '/api/labels/subjects/order/5/', { body: [{ id: 1, name: 'Срочно', color: 'red' }, { id: 2, name: 'VIP', color: 'blue' }] }]])
    renderApp('/orders/5')
    expect(await screen.findByTitle('Срочно')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Изменить метки' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: 'VIP' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')!.body).toEqual({ labels: [1, 2] })
  })

  it('в окне можно сразу создать метку (labels.manage) и она отмечается', async () => {
    const m = loggedIn([
      ...orderRoutes([]),
      ['POST', '/api/labels/', { status: 201, body: { id: 9, name: 'Хрупкое', color: 'blue', usage_count: 0, created_at: '2026-11-02T00:00:00Z' } }],
    ])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить метки' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Новая метка'), 'Хрупкое')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/labels/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')!.body).toEqual({ name: 'Хрупкое', color: 'blue' })
  })

  it('без orders.update кнопки выбора меток нет, чипы видны', async () => {
    loggedIn(orderRoutes([{ id: 1, name: 'Срочно', color: 'red' }]), { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'orders.update') } })
    renderApp('/orders/5')
    expect(await screen.findByTitle('Срочно')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Изменить метки' })).not.toBeInTheDocument()
  })
})

describe('Метки в списке и фильтр', () => {
  it('чипы в списке заказов; фильтр по метке уходит параметром label', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/orders\/\?/, { body: page([{ ...makeOrder(), labels: [{ id: 1, name: 'Срочно', color: 'red' }] }]) }],
      ['GET', '/api/labels/', { body: [RED, BLUE] }],
    ])
    renderApp('/orders?label=2')
    expect(await screen.findByTitle('Срочно')).toBeInTheDocument()
    const q = new URL(m.calls.find((c) => c.path.startsWith('/api/orders/?'))!.path, 'http://x').searchParams
    expect(q.get('label')).toBe('2')
    expect(await screen.findByLabelText('Метка')).toHaveValue('2')
  })
})
