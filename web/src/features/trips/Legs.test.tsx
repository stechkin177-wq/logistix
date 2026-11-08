import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, ORDER_STATUSES, handbookBody, makeConsignment, makeOrder } from '../../test/orders'
import { renderApp } from '../../test/renderApp'
import { TRIP_STATUSES, makeCargo, makeTrip } from '../../test/trips'
import type { ConsignmentRoute, OrderStop } from '../orders/types'
import type { TripLeg } from './types'

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

const STOPS = [stop(1, 1, 'load', 'Алматы'), stop(2, 2, 'transit', 'Караганда'), stop(3, 3, 'unload', 'Астана')]

function route(coveredFirst: boolean, coveredSecond: boolean): ConsignmentRoute {
  const seg = (from: number, to: number, covered: boolean, trips: { id: number; number: string; status: string }[]) => ({
    from_stop: from, to_stop: to, from_seq: from, to_seq: to, covered, legs: covered ? [7] : [], trips: covered ? trips : [],
  })
  const segments = [
    seg(1, 2, coveredFirst, [{ id: 90, number: 'ORD-5-1', status: 'planned' }]),
    seg(2, 3, coveredSecond, [{ id: 91, number: 'ORD-5-2', status: 'planned' }]),
  ]
  return { stops: STOPS, coverage: { segments, uncovered: segments.filter((s) => !s.covered), fully_assigned: segments.every((s) => s.covered) } }
}

const LEGS: TripLeg[] = [
  { id: 7, consignment: 31, consignment_name: 'Станки', order: 5, order_number: 'ORD-2026-00005', from_stop: { id: 1, seq: 1, kind: 'load', city: 'Алматы' }, to_stop: { id: 2, seq: 2, kind: 'transit', city: 'Караганда' }, leg_seq: 1, status: 'planned', weight_kg: '400.00', volume_m3: null, pallets: null },
  { id: 8, consignment: 31, consignment_name: 'Станки', order: 5, order_number: 'ORD-2026-00005', from_stop: { id: 2, seq: 2, kind: 'transit', city: 'Караганда' }, to_stop: { id: 3, seq: 3, kind: 'unload', city: 'Астана' }, leg_seq: 2, status: 'done', weight_kg: null, volume_m3: null, pallets: null },
]

describe('Карточка рейса: участки', () => {
  const open = async (trip = makeTrip({ legs: LEGS })) => {
    const routes: MockRoutes = [
      ['GET', /^\/api\/trips\/\?/, { body: page([trip]) }],
      ['GET', '/api/trips/90/', { body: trip }],
      ['GET', '/api/handbooks/?code=trip_status', { body: handbookBody('trip_status', TRIP_STATUSES) }],
      ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
    ]
    loggedIn(routes)
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: 'ORD-2026-00005-1' }))
    return await screen.findByRole('dialog')
  }

  it('участки: откуда-куда, груз, доли и статус', async () => {
    const dialog = await open()
    const legs = within(await within(dialog).findByRole('region', { name: 'Участки' }))
    const items = legs.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Станки')
    expect(items[0]).toHaveTextContent('Алматы → Караганда')
    expect(items[0]).toHaveTextContent('400.00 кг')
    expect(items[0]).toHaveTextContent('Запланирован')
    expect(items[1]).toHaveTextContent('Караганда → Астана')
    expect(items[1]).toHaveTextContent('весь груз')
    expect(items[1]).toHaveTextContent('Выполнен')
  })

  it('прежняя связь без остановок показана как «Весь маршрут»; без legs блока нет', async () => {
    const legacy: TripLeg = { ...LEGS[0]!, from_stop: null, to_stop: null, weight_kg: null }
    const dialog = await open(makeTrip({ legs: [legacy] }))
    expect(await within(dialog).findByText(/Весь маршрут/)).toBeInTheDocument()
  })

  it('ответ без поля legs (старый API) - карточка открывается без блока участков', async () => {
    const dialog = await open(makeTrip())
    await within(dialog).findByLabelText('Госномер')
    expect(within(dialog).queryByRole('region', { name: 'Участки' })).not.toBeInTheDocument()
  })
})

describe('Карточка заказа: лента маршрута с покрытием', () => {
  const common = [
    ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
    ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
    ['GET', '/api/users/', { body: [] }],
    ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
  ] as MockRoutes

  it('непокрытый отрезок подсвечен, покрытый показывает номер рейса; итог - сколько не назначено', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder({ consignments: [makeConsignment({ stops: STOPS, route: route(true, false) })] }) }],
      ...common,
    ])
    renderApp('/orders/5?tab=cargo')
    const lane = await screen.findByRole('list', { name: 'Маршрут с назначением рейсов' })
    const marks = within(lane).getAllByText(/ORD-5-1|Рейс не назначен/)
    expect(marks.map((m) => [m.textContent, m.getAttribute('data-covered')])).toEqual([
      ['ORD-5-1', 'yes'],
      ['Рейс не назначен', 'no'],
    ])
    expect(screen.getByText('Не назначено отрезков: 1')).toBeInTheDocument()
  })

  it('все отрезки покрыты - плашка «Все отрезки назначены на рейсы»', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder({ consignments: [makeConsignment({ stops: STOPS, route: route(true, true) })] }) }],
      ...common,
    ])
    renderApp('/orders/5?tab=cargo')
    expect(await screen.findByText('Все отрезки назначены на рейсы')).toBeInTheDocument()
  })
})

describe('Создание рейса: выбор участков', () => {
  const cargo = makeCargo({ id: 31, name: 'Станки', order: 5, order_number: 'ORD-5', stops: STOPS })
  const simple = makeCargo({ id: 32, name: 'Ящики', order: 5, order_number: 'ORD-5' })
  const routes = (rows = [cargo, simple]): MockRoutes => [
    ['GET', /^\/api\/consignments\/\?/, { body: page(rows) }],
    ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
    ['POST', '/api/trips/', { status: 201, body: makeTrip({ id: 92, number: 'ORD-5-3' }) }],
  ]
  const openDrawer = async () => {
    const m = loggedIn(routes())
    renderApp('/consignments')
    await screen.findByText('Станки')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все на странице' }))
    await userEvent.click(screen.getByRole('button', { name: 'Создать рейс' }))
    return { m, dialog: await screen.findByRole('dialog') }
  }

  it('выбор участка предлагается только грузу с несколькими остановками', async () => {
    const { dialog } = await openDrawer()
    expect(within(dialog).getAllByRole('checkbox', { name: 'Выбрать участок' })).toHaveLength(1)
  })

  it('без выбора участка тело прежнее: consignments, без legs', async () => {
    const { m, dialog } = await openDrawer()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/trips/')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'POST' && c.path === '/api/trips/')!.body as Record<string, unknown>
    expect(body.consignments).toEqual([31, 32])
    expect(body).not.toHaveProperty('legs')
  })

  it('с выбранным участком груз уходит в legs с остановками и долями, остальные - в consignments', async () => {
    const { m, dialog } = await openDrawer()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Выбрать участок' }))
    await userEvent.selectOptions(within(dialog).getByLabelText('Докуда'), '2')
    await userEvent.type(within(dialog).getByLabelText('Вес, кг'), '400')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/trips/')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'POST' && c.path === '/api/trips/')!.body as Record<string, unknown>
    expect(body.consignments).toEqual([32])
    expect(body.legs).toEqual([{ consignment: 31, from_stop: 1, to_stop: 2, shares: { weight_kg: '400' } }])
  })

  it('участок «назад» не отправляется: ошибка на форме', async () => {
    const { m, dialog } = await openDrawer()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Выбрать участок' }))
    await userEvent.selectOptions(within(dialog).getByLabelText('Докуда'), '1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }))
    expect(await within(dialog).findByText('Начало участка должно быть раньше конца')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })
})
