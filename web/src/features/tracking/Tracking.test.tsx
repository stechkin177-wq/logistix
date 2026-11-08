import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, ORDER_STATUSES, handbookBody, makeConsignment, makeOrder } from '../../test/orders'
import { renderApp } from '../../test/renderApp'
import type { OrderStop } from '../orders/types'
import type { CargoTransfer, ConsignmentEvent } from './types'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stop(id: number, seq: number, kind: OrderStop['kind'], city: string): OrderStop {
  return {
    id, seq, kind, status: 'planned', arrived_at: null, done_at: null, weight_kg: null, volume_m3: null, pallets: null,
    window_from: '2026-11-05T04:00:00Z', window_to: null, country: null, country_name: null, city, street: '', method: null,
    method_name: null, contact: '', postal_code: '', lat: null, lng: null, note: '',
  }
}

const STOPS = [stop(1, 1, 'load', 'Алматы'), stop(2, 2, 'transfer', 'Караганда'), stop(3, 3, 'unload', 'Астана')]

const EVENT: ConsignmentEvent = {
  id: 1, consignment: 31, stop: 1, stop_seq: 1, stop_city: 'Алматы', leg: null, trip: null, trip_number: null, event_type: 'arrived',
  event_type_name: 'Прибыл на остановку', occurred_at: '2026-11-05T05:00:00Z', recorded_by: 1, source: 'driver_app', note: '', created_at: '2026-11-05T05:00:00Z',
}

function transfer(over: Partial<CargoTransfer> = {}): CargoTransfer {
  return {
    id: 8, consignment: 31, consignment_name: 'Станки', order: 5, order_number: 'ORD-2026-00005', transfer_kind: 'to_storage',
    transfer_kind_name: 'На склад', from_trip: 90, from_trip_number: 'ORD-5-1', to_trip: null, to_trip_number: null, from_stop: null, to_stop: 2,
    to_stop_city: 'Караганда', from_carrier: 6, from_carrier_name: 'ИП Быстров', to_carrier: null, to_carrier_name: null, carrier_changed: false,
    transferred_at: '2026-11-06T05:00:00Z', weight_kg: null, volume_m3: null, pallets: null, status: 'initiated', initiated_by: 1, source: 'manual',
    confirmed_by: null, confirmed_at: null, reverses: null, reversed_by: null, note: '', created_at: '2026-11-06T05:00:00Z', ...over,
  }
}

const common = [
  ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
  ['GET', '/api/users/', { body: [] }],
  ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
] as MockRoutes

describe('Карточка груза: местонахождение, события, передача', () => {
  const open = (extra: MockRoutes = [], location: 'in_storage' | 'planned' = 'in_storage') => {
    const m = loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder({ consignments: [makeConsignment({ stops: STOPS, location_status: location })] }) }],
      ['GET', '/api/consignments/31/events/', { body: [EVENT] }],
      ['GET', '/api/consignments/31/transfers/', { body: [transfer({ status: 'confirmed' })] }],
      ...extra,
      ...common,
    ])
    renderApp('/orders/5?tab=cargo')
    return m
  }

  it('бейдж местонахождения, лента событий и передачи', async () => {
    open()
    expect(await screen.findByText('На хранении')).toBeInTheDocument()
    const events = await screen.findByRole('list', { name: 'События груза' })
    expect(events).toHaveTextContent('Прибыл на остановку, Алматы')
    expect(events).toHaveTextContent('из приложения водителя')
    const transfers = await screen.findByRole('list', { name: 'Передачи' })
    expect(transfers).toHaveTextContent('На склад, Караганда')
    expect(transfers).toHaveTextContent('Подтверждена')
  })

  it('диалог «Передать груз»: на склад без рейса, тело без to_trip', async () => {
    const m = open([['POST', '/api/consignments/31/transfers/', { status: 201, body: transfer() }]], 'planned')
    await userEvent.click(await screen.findByRole('button', { name: 'Передать груз' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByLabelText('Следующий рейс (id)')).not.toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Рейс отправления (id)'), '90')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Передать' }))
    await waitFor(() => { expect(m.count('POST', '/api/consignments/31/transfers/')).toBe(1) })
    const body = m.calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>
    expect(body).toMatchObject({ transfer_kind: 'to_storage', to_stop: 2, from_trip: 90, to_trip: null })
  })

  it('ошибка сервера показывается в диалоге', async () => {
    open([['POST', '/api/consignments/31/transfers/', { status: 400, body: { to_trip: 'У груза нет участка этого рейса' } }]], 'planned')
    await userEvent.click(await screen.findByRole('button', { name: 'Передать груз' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Передать' }))
    expect(await within(dialog).findByText(/У груза нет участка/)).toBeInTheDocument()
  })
})

describe('Список передач', () => {
  it('подтверждение и сторно доступны с правом consignments.transfer', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/transfers\/\?/, { body: page([transfer(), transfer({ id: 9, status: 'confirmed', carrier_changed: true, to_carrier_name: 'ИП Новый' })]) }],
      ['POST', '/api/transfers/8/confirm/', { body: transfer({ status: 'confirmed' }) }],
    ])
    renderApp('/transfers')
    await screen.findByText('ИП Новый', { exact: false })
    const rows = screen.getAllByRole('row')
    expect(rows.length).toBe(3)
    expect(rows[2]).toHaveTextContent('перевозчик сменился')
    await userEvent.click(within(rows[1]!).getByRole('button', { name: 'Подтвердить' }))
    await waitFor(() => { expect(m.count('POST', '/api/transfers/8/confirm/')).toBe(1) })
  })

  it('без права consignments.transfer кнопок действий нет', async () => {
    loggedIn(
      [['GET', /^\/api\/transfers\/\?/, { body: page([transfer()]) }]],
      { session: { permissions: ['consignments.view'] } },
    )
    renderApp('/transfers')
    await screen.findByText('Ждёт подтверждения')
    expect(screen.queryByRole('button', { name: 'Подтвердить' })).not.toBeInTheDocument()
  })
})
