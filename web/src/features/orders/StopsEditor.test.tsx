import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, ORDER_STATUSES, handbookBody, makeConsignment, makeOrder } from '../../test/orders'
import { renderApp } from '../../test/renderApp'
import {
  canSimplify, consignmentFromApi, consignmentPayload, emptyConsignment, isMultiStop, validateConsignment,
} from './orderForm'
import type { OrderStop } from './types'

const t = (key: string) => key

function stop(seq: number, kind: OrderStop['kind'], city: string, over: Partial<OrderStop> = {}): OrderStop {
  return {
    id: 100 + seq, seq, kind, status: 'planned', arrived_at: null, done_at: null, weight_kg: null, volume_m3: null, pallets: null,
    window_from: `2026-11-0${String(4 + seq)}T04:00:00Z`, window_to: null, country: null, country_name: null, city, street: '',
    method: null, method_name: null, contact: '', postal_code: '', lat: null, lng: null, note: '', ...over,
  }
}

const THREE = [stop(1, 'load', 'Алматы'), stop(2, 'transit', 'Караганда', { weight_kg: '400.00' }), stop(3, 'unload', 'Астана')]

describe('форма остановок: данные', () => {
  it('груз с двумя остановками - простой маршрут (points), с тремя - расширенный (stops)', () => {
    expect(consignmentFromApi(makeConsignment(), 'UTC').stops).toBeNull()
    const two = makeConsignment({ stops: [stop(1, 'load', 'А'), stop(2, 'unload', 'Б')] })
    expect(consignmentFromApi(two, 'UTC').stops).toBeNull()
    const multi = consignmentFromApi(makeConsignment({ stops: THREE }), 'UTC')
    expect(multi.stops?.map((s) => [s.id, s.kind, s.city, s.weight_kg])).toEqual([
      [101, 'load', 'Алматы', ''], [102, 'transit', 'Караганда', '400.00'], [103, 'unload', 'Астана', ''],
    ])
    expect(isMultiStop(THREE)).toBe(true)
    expect(isMultiStop([stop(1, 'load', 'А'), stop(2, 'unload', 'Б')])).toBe(false)
  })

  it('простой маршрут уходит в points, расширенный - в stops с id и долями (пусто = null)', () => {
    const simple = consignmentPayload(consignmentFromApi(makeConsignment(), 'UTC'), 'UTC')
    expect(simple).toHaveProperty('points')
    expect(simple).not.toHaveProperty('stops')
    const body = consignmentPayload(consignmentFromApi(makeConsignment({ stops: THREE }), 'UTC'), 'UTC') as unknown as {
      stops: { id: number; kind: string; weight_kg: string | null; pallets: number | null }[]
    }
    expect(body).not.toHaveProperty('points')
    expect(body.stops.map((s) => [s.id, s.kind, s.weight_kg, s.pallets])).toEqual([
      [101, 'load', null, null], [102, 'transit', '400.00', null], [103, 'unload', null, null],
    ])
  })

  it('проверка: маршрут начинается с погрузки и заканчивается выгрузкой; доли - числа', () => {
    const form = consignmentFromApi(makeConsignment({ stops: THREE }), 'UTC')
    const ok: Record<string, string> = {}
    form.name = 'Станки'; form.weight_kg = '10'; form.volume_m3 = '1'
    validateConsignment(form, 'c', t, ok)
    expect(ok).toEqual({})
    const stops = form.stops ?? []
    const bad = { ...form, stops: [stops[1]!, stops[0]!, stops[2]!] }
    const errors: Record<string, string> = {}
    validateConsignment(bad, 'c', t, errors)
    expect(errors['c.stops']).toBe('orders.routeEdges')
    const shares = { ...form, stops: stops.map((s, i) => (i === 1 ? { ...s, weight_kg: 'abc' } : s)) }
    const errs: Record<string, string> = {}
    validateConsignment(shares, 'c', t, errs)
    expect(errs['c.stops.1.weight_kg']).toBe('errors.invalidNumber')
  })

  it('свернуть можно только погрузку и выгрузку', () => {
    const form = consignmentFromApi(makeConsignment({ stops: THREE }), 'UTC')
    expect(canSimplify(form.stops ?? [])).toBe(false)
    expect(canSimplify((form.stops ?? []).filter((s) => s.kind !== 'transit'))).toBe(true)
    expect(emptyConsignment().stops).toBeNull()
  })
})

const base = [
  ['GET', /^\/api\/clients\/\?/, { body: page([{ id: 7, name: 'ТОО Ромашка' }]) }],
  ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
  ['GET', '/api/users/', { body: [{ user_id: 1, full_name: 'Админ Админов', email: 'a@x.kz', phone: null, is_active: true }] }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
] as MockRoutes

describe('Новый заказ: несколько остановок', () => {
  it('кнопка «Несколько остановок» превращает маршрут в список; новая остановка встаёт перед выгрузкой; в теле stops', async () => {
    const m = loggedIn([...base, ['POST', '/api/orders/', { status: 201, body: makeOrder() }], ['GET', '/api/orders/5/', { body: makeOrder() }]])
    const { router } = renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await userEvent.click(screen.getByRole('combobox', { name: /Клиент/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'ТОО Ромашка' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить груз' }))
    const cargo = screen.getByRole('region', { name: 'Груз' })
    await userEvent.type(within(cargo).getByLabelText(/Название груза/), 'Станки')
    await userEvent.type(within(cargo).getByLabelText(/Вес, кг/), '1200')
    await userEvent.type(within(cargo).getByLabelText(/Объём/), '8.5')
    const route = within(screen.getByRole('region', { name: 'Маршрут' }))
    await userEvent.click(route.getByRole('button', { name: 'Несколько остановок' }))
    await userEvent.click(route.getByRole('button', { name: 'Добавить остановку' }))
    const first = within(route.getByRole('region', { name: 'Остановка 1' }))
    const second = within(route.getByRole('region', { name: 'Остановка 2' }))
    const third = within(route.getByRole('region', { name: 'Остановка 3' }))
    expect(first.getByRole('combobox', { name: 'Вид остановки' })).toHaveValue('load')
    expect(second.getByRole('combobox', { name: 'Вид остановки' })).toHaveValue('transit')
    expect(third.getByRole('combobox', { name: 'Вид остановки' })).toHaveValue('unload')
    // свернуть нельзя: остановок три
    expect(route.getByRole('button', { name: 'Простой маршрут (погрузка и выгрузка)' })).toBeDisabled()
    for (const [section, day, city] of [[first, '05', 'Алматы'], [second, '06', 'Караганда'], [third, '08', 'Астана']] as const) {
      fireEvent.change(section.getByLabelText(/Окно с/), { target: { value: `2026-11-${day}T09:00` } })
      await userEvent.type(section.getByLabelText(/Город/), city)
    }
    await userEvent.type(second.getByLabelText('Вес, кг'), '400')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(router.state.location.pathname).toBe('/orders/5') })
    const body = m.calls.find((c) => c.method === 'POST')!.body as { consignments: { stops: { kind: string; city: string; weight_kg: string | null }[] }[] }
    expect(body.consignments[0]).not.toHaveProperty('points')
    expect(body.consignments[0]!.stops.map((s) => [s.kind, s.city, s.weight_kg])).toEqual([
      ['load', 'Алматы', null], ['transit', 'Караганда', '400'], ['unload', 'Астана', null],
    ])
  })

  it('порядок меняется кнопками, удаление недоступно при двух остановках, ошибка сервера stops.1.city ложится на поле', async () => {
    loggedIn([
      ...base,
      ['POST', '/api/orders/', { status: 400, body: { consignments: [{ stops: [{}, { city: ['Укажите город (сервер)'] }, {}] }] } }],
    ])
    renderApp('/orders/new')
    await screen.findByRole('region', { name: 'Контакты' })
    await userEvent.click(screen.getByRole('combobox', { name: /Клиент/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'ТОО Ромашка' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добавить груз' }))
    const cargo = screen.getByRole('region', { name: 'Груз' })
    await userEvent.type(within(cargo).getByLabelText(/Название груза/), 'Станки')
    await userEvent.type(within(cargo).getByLabelText(/Вес, кг/), '10')
    await userEvent.type(within(cargo).getByLabelText(/Объём/), '1')
    const route = within(screen.getByRole('region', { name: 'Маршрут' }))
    await userEvent.click(route.getByRole('button', { name: 'Несколько остановок' }))
    expect(route.getByRole('button', { name: 'Убрать остановку 1' })).toBeDisabled()
    await userEvent.click(route.getByRole('button', { name: 'Добавить остановку' }))
    await userEvent.type(within(route.getByRole('region', { name: 'Остановка 2' })).getByLabelText(/Город/), 'Караганда')
    await userEvent.click(route.getByRole('button', { name: 'Опустить остановку 2' }))
    expect(within(route.getByRole('region', { name: 'Остановка 3' })).getByLabelText(/Город/)).toHaveValue('Караганда')
    expect(route.getByRole('button', { name: 'Опустить остановку 3' })).toBeDisabled()
    // маршрут теперь заканчивается транзитом: проверка до отправки
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Маршрут должен начинаться с погрузки и заканчиваться выгрузкой')).toBeInTheDocument()
  })
})

describe('Карточка заказа: маршрут цепочкой', () => {
  const common = [
    ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
    ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
    ['GET', '/api/users/', { body: [] }],
    ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
  ] as MockRoutes

  it('груз с тремя остановками показывает цепочку и все остановки; простой груз - как раньше', async () => {
    loggedIn([
      ['GET', '/api/orders/5/', { body: makeOrder({ consignments: [makeConsignment({ id: 31, name: 'Станки', stops: THREE }), makeConsignment({ id: 32, name: 'Мука' })] }) }],
      ...common,
    ])
    renderApp('/orders/5?tab=cargo')
    const chain = await screen.findByRole('list', { name: 'Маршрут груза' })
    expect(within(chain).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Алматы · Погрузка', '→Караганда · Промежуточная остановка', '→Астана · Выгрузка',
    ])
    expect(screen.getAllByRole('list', { name: 'Маршрут груза' })).toHaveLength(1) // у простого груза цепочки нет
  })
})
