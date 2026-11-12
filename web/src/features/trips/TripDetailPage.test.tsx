import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody } from '../../test/orders'
import { renderApp } from '../../test/renderApp'
import { TRIP_STATUSES, makeTrip } from '../../test/trips'

const base = (trip = makeTrip()): MockRoutes => [
  ['GET', '/api/trips/90/', { body: trip }],
  ['GET', '/api/handbooks/?code=trip_status', { body: handbookBody('trip_status', TRIP_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
]

describe('Страница рейса', () => {
  it('сводка и вкладки: перевозчик-ссылка, заказы, состав, счётчики', async () => {
    loggedIn(base())
    renderApp('/trips/90')
    expect(await screen.findByRole('heading', { name: 'ORD-2026-00005-1' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(within(main).getByRole('link', { name: 'ИП Быстров' })).toHaveAttribute('href', '/carriers/6')
    expect(within(main).getByRole('link', { name: 'ORD-2026-00005' })).toHaveAttribute('href', '/orders/5')
    expect(within(main).getByText('грузов: 1 · участков: 0')).toBeInTheDocument()
    expect(within(main).getByRole('tab', { name: /Грузы\s*1/ })).toBeInTheDocument()
    expect(within(main).getByRole('link', { name: /Назад: Рейсы/ })).toHaveAttribute('href', '/trips')
  })

  it('вкладка «История» читает журнал аудита по forwarding.trip и id рейса', async () => {
    const m = loggedIn([
      ...base(),
      ['GET', /^\/api\/audit\//, { body: { count: 1, next: null, previous: null, results: [
        { id: 1, user: null, action: 'update', object_type: 'forwarding.trip', object_id: '90', object_repr: 'x', changes: { driver_name: ['Иван', 'Пётр'] }, changes_labels: {}, created_at: '2026-11-01T09:00:00Z' },
      ] } }],
      ['GET', '/api/users/', { body: [] }],
    ])
    renderApp('/trips/90')
    await userEvent.click(await screen.findByRole('tab', { name: 'История' }))
    expect(await screen.findByText('driver_name:')).toBeInTheDocument()
    expect(screen.getByText('Пётр')).toBeInTheDocument()
    const q = new URL(m.calls.find((c) => c.path.startsWith('/api/audit/'))!.path, 'http://x').searchParams
    expect(q.get('object_type')).toBe('forwarding.trip')
    expect(q.get('object_id')).toBe('90')
  })

  it('старая ссылка /trips?open=90 ведёт на страницу рейса', async () => {
    loggedIn(base())
    const { router } = renderApp('/trips?open=90')
    await screen.findByRole('heading', { name: 'ORD-2026-00005-1' })
    expect(router.state.location.pathname).toBe('/trips/90')
  })

  it('несуществующий рейс - пустое состояние', async () => {
    loggedIn([['GET', '/api/trips/404/', { status: 404, body: { detail: 'Не найдено.' } }], ...base()])
    renderApp('/trips/404')
    expect(await screen.findByText('Рейс не найден')).toBeInTheDocument()
  })
})
