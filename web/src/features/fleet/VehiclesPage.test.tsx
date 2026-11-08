import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const MODULES = ['logistics', 'fleet', 'documents']
const VEHICLE = {
  id: 3, kind: 'tractor', plate: '777AAA01', vin: '', make: 'Volvo', model: 'FH', year: 2020, body_type: '', capacity_kg: null,
  volume_m3: null, status: 'active', gps_check: true, notes: '', documents: [], insurances: [],
}
const REMINDERS = {
  count: 2,
  results: [
    { type: 'insurance', state: 'overdue', vehicle: 3, plate: '777AAA01', title: 'ОСАГО', due_date: '2026-10-01', due_km: null, current_km: 1000 },
    { type: 'service', state: 'due_soon', vehicle: 3, plate: '777AAA01', title: 'Замена масла', due_date: null, due_km: 1500, current_km: 1000 },
  ],
}
const base: MockRoutes = [
  ['GET', /^\/api\/vehicles\/\?/, { body: page([VEHICLE]) }],
  ['GET', '/api/fleet/reminders/', { body: REMINDERS }],
]

describe('Техника', () => {
  it('список, предупреждения на главном экране и отметка у машины', async () => {
    loggedIn([...base], { session: { modules: MODULES } })
    renderApp('/vehicles')
    expect(await screen.findByText('Volvo FH')).toBeInTheDocument()
    const warnings = await screen.findByRole('region', { name: 'Требует внимания' })
    expect(within(warnings).getByText(/ОСАГО/)).toBeInTheDocument()
    expect(within(warnings).getByText(/Замена масла/)).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText(/Просрочено: 2/)).toBeInTheDocument()
  })

  it('карточка: шесть вкладок и сверка пробега по GPS без данных', async () => {
    loggedIn(
      [
        ...base,
        ['GET', '/api/vehicles/3/mileage-check/', { body: { enabled: true, official_km: 1000, gps_km: null, gps_available: false, difference_km: null, threshold_km: 100, warning: false } }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/vehicles')
    await userEvent.click(await screen.findByRole('button', { name: '777AAA01' }))
    const drawer = await screen.findByRole('dialog')
    const tabs = within(drawer).getAllByRole('tab').map((x) => x.textContent)
    expect(tabs).toEqual(['Основное', 'Документы', 'Страхование', 'Обслуживание и ремонты', 'Заправки и расход', 'Пробег'])
    const check = await within(drawer).findByRole('region', { name: 'Сверка пробега' })
    expect(within(check).getByText(/Официальный пробег, км: 1000/)).toBeInTheDocument()
    expect(within(check).getByText('Данные GPS недоступны')).toBeInTheDocument()
  })

  it('сверка пробега с расхождением показывает предупреждение', async () => {
    loggedIn(
      [
        ...base,
        ['GET', '/api/vehicles/3/mileage-check/', { body: { enabled: true, official_km: 1000, gps_km: 1300, gps_available: true, difference_km: 300, threshold_km: 100, warning: true } }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/vehicles')
    await userEvent.click(await screen.findByRole('button', { name: '777AAA01' }))
    const check = await screen.findByRole('region', { name: 'Сверка пробега' })
    expect(await within(check).findByText('Расхождение больше 100 км')).toBeInTheDocument()
  })

  it('вкладка заправок: средний расход и добавление записи с привязкой к технике', async () => {
    const m = loggedIn(
      [
        ...base,
        ['GET', '/api/vehicles/3/mileage-check/', { body: { enabled: false } }],
        ['GET', '/api/vehicles/3/fuel-stats/', { body: { average_l_per_100km: '28.75', distance_km: 800 } }],
        ['GET', /^\/api\/fuel-fills\/\?/, { body: page([]) }],
        ['POST', '/api/fuel-fills/', { status: 201, body: { id: 1 } }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/vehicles')
    await userEvent.click(await screen.findByRole('button', { name: '777AAA01' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('tab', { name: 'Заправки и расход' }))
    expect(await within(drawer).findByText('28.75 л/100 км')).toBeInTheDocument()
    await userEvent.click(within(drawer).getByRole('button', { name: 'Добавить' }))
    expect(await within(drawer).findByText(/Дата и время заправки: Обязательное поле/)).toBeInTheDocument()
    await userEvent.type(within(drawer).getByLabelText('Дата и время заправки'), '2026-06-01T08:00')
    await userEvent.type(within(drawer).getByLabelText('Литры'), '120')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Добавить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/fuel-fills/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST' && c.path === '/api/fuel-fills/')!.body).toMatchObject({ vehicle: 3, liters: 120, full_tank: true })
  })

  it('вкладка «Пробег» только для чтения и объясняет правило официального пробега', async () => {
    loggedIn(
      [
        ...base,
        ['GET', '/api/vehicles/3/mileage-check/', { body: { enabled: false } }],
        ['GET', /^\/api\/mileage\/\?/, { body: page([{ id: 1, vehicle: 3, trip: 9, recorded_at: '2026-06-01T10:00:00Z', odometer_km: 100500, source: 'trip_start', note: '' }]) }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/vehicles')
    await userEvent.click(await screen.findByRole('button', { name: '777AAA01' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('tab', { name: 'Пробег' }))
    expect(await within(drawer).findByText(/Выезд в рейс · 100500 км/)).toBeInTheDocument()
    expect(within(drawer).getByText(/только при выезде в рейс и по завершении рейса/)).toBeInTheDocument()
    expect(within(drawer).queryByRole('button', { name: 'Добавить' })).not.toBeInTheDocument()
  })

  it('без модуля fleet пункта меню «Техника» нет', async () => {
    loggedIn([], { session: { modules: ['logistics'] } })
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByText('Техника')).not.toBeInTheDocument()
  })
})
