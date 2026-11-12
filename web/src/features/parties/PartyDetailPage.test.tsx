import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const CLIENT = {
  id: 7, name: 'ТОО Ромашка', bin_iin: '123456789012', type: null, type_name: 'Юридическое лицо', status: 'active',
  credit_limit: '1000.00', orders_count: 2, notes: '', address: '', bank: '', iban: '',
  contacts: [{ id: 5, name: 'Иван', position: '', phone: '', email: '' }], created_at: '2026-10-01T05:00:00Z',
}
const CARRIER = { ...CLIENT, id: 3, name: 'ИП Быстров', rating: '4.5', credit_limit: undefined, orders_count: undefined }
const empty = { count: 0, next: null, previous: null, results: [] }

describe('Карточка клиента', () => {
  it('шапка, вкладки со счётчиками, последние заказы и ссылка на все заказы', async () => {
    loggedIn([
      ['GET', '/api/clients/7/', { body: CLIENT }],
      ['GET', /^\/api\/orders\/\?/, { body: page([{ id: 11, number: 'ORD-11', route: 'Алматы → Астана', status_name: 'Новый', client_rate: '5000.00', currency: 1 }]) }],
      ['GET', /^\/api\/handbooks\/\?code=client_type/, { body: { code: 'client_type', name: 'x', group: 'g', values: [] } }],
    ])
    renderApp('/clients/7?tab=work')
    expect(await screen.findByRole('heading', { name: 'ТОО Ромашка' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(within(main).getByRole('tab', { name: /Контакты\s*1/ })).toBeInTheDocument()
    expect(within(main).getByRole('tab', { name: /Заказы\s*2/ })).toBeInTheDocument()
    expect(await within(main).findByRole('link', { name: 'ORD-11' })).toHaveAttribute('href', '/orders/11')
    expect(within(main).getByRole('link', { name: 'Все заказы' })).toHaveAttribute('href', '/orders?client=7')
  })

  it('несуществующий клиент - пустое состояние со ссылкой на список', async () => {
    loggedIn([['GET', '/api/clients/99/', { status: 404, body: { detail: 'Не найдено.' } }]])
    renderApp('/clients/99')
    expect(await screen.findByText('Клиент не найден')).toBeInTheDocument()
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Клиенты' })).toHaveAttribute('href', '/clients')
  })

  it('удаление из карточки: подтверждение, DELETE и возврат к списку', async () => {
    const m = loggedIn([
      ['GET', '/api/clients/7/', { body: CLIENT }],
      ['DELETE', '/api/clients/7/', { status: 204 }],
      ['GET', /^\/api\/clients\/\?/, { body: page([]) }],
      ['GET', /^\/api\/handbooks\/\?code=client_type/, { body: { code: 'client_type', name: 'x', group: 'g', values: [] } }],
    ])
    const { router } = renderApp('/clients/7')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE' && c.path === '/api/clients/7/')).toBe(true) })
    await waitFor(() => { expect(router.state.location.pathname).toBe('/clients') })
  })
})

describe('Карточка перевозчика', () => {
  it('вкладка «Рейсы» показывает рейсы перевозчика и запрашивает их по carrier', async () => {
    const m = loggedIn([
      ['GET', '/api/carriers/3/', { body: CARRIER }],
      ['GET', /^\/api\/trips\/\?/, { body: page([{ id: 90, number: 'TRP-90', vehicle_plate: '123ABC', driver_name: 'Иван', status_name: 'В пути', carrier_price: '100000.00', currency: 1 }]) }],
      ['GET', /^\/api\/handbooks\/\?code=carrier_type/, { body: { code: 'carrier_type', name: 'x', group: 'g', values: [] } }],
    ])
    renderApp('/carriers/3?tab=work')
    expect(await screen.findByRole('link', { name: 'TRP-90' })).toHaveAttribute('href', '/trips/90')
    const call = m.calls.find((c) => c.path.startsWith('/api/trips/?'))!
    expect(new URL(call.path, 'http://x').searchParams.get('carrier')).toBe('3')
  })

  it('вкладка «История» без права company.view объясняет, почему пусто', async () => {
    loggedIn(
      [
        ['GET', '/api/carriers/3/', { body: CARRIER }],
        ['GET', /^\/api\/handbooks\/\?code=carrier_type/, { body: { code: 'carrier_type', name: 'x', group: 'g', values: [] } }],
        ['GET', /^\/api\/audit\//, { body: empty }],
      ],
      { session: { permissions: ['carriers.view', 'carriers.update'] } },
    )
    renderApp('/carriers/3?tab=history')
    expect(await screen.findByText('История недоступна')).toBeInTheDocument()
  })
})
