import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeSession, page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'
import { parsePolygon } from './GeofencesTab'

// Leaflet в jsdom не рисуется: вместо карты - заглушка, показывающая, что ей передали
vi.mock('./GpsMap', () => ({
  default: ({ units, geofences, track }: { units: unknown[]; geofences: unknown[]; track: unknown[] }) => (
    <div data-testid="map-stub">{`units=${String(units.length)} zones=${String(geofences.length)} track=${String(track.length)}`}</div>
  ),
}))

const MODULES = { modules: ['logistics', 'fleet', 'gps'] }
const UNIT = {
  id: 1, unit_id: '501', name: 'Volvo 886 AIA 14', vehicle: 7, vehicle_plate: '886AIA14', lat: '43.238900', lon: '76.945600', speed_kmh: 62,
  position_at: '2026-11-18T08:00:00Z', location_text: 'Алматы, пр. Аль-Фараби', odometer_km: '123456.7', odometer_at: '2026-11-18T08:00:00Z',
  fuel_level_l: '310.5', fuel_level_at: '2026-11-18T08:00:00Z', seen_at: '2026-11-18T08:00:00Z',
}
const FREE = { ...UNIT, id: 2, unit_id: '502', name: 'Неизвестный', vehicle: null, vehicle_plate: null, lat: null, lon: null, speed_kmh: null, odometer_km: null, fuel_level_l: null }
const VEHICLES = page([{ id: 7, plate: '886AIA14', kind: 'tractor', status: 'active' }, { id: 8, plate: '777BBB02', kind: 'truck', status: 'active' }])
const GEO = { id: 3, name: 'Склад Алматы', kind: 'warehouse', shape: 'circle', lat: '43.2', lon: '76.9', radius_m: 300, polygon: null, is_active: true, source: 'wialon', is_approximate: false }

const base = () => [['GET', /^\/api\/vehicles\//, { body: VEHICLES }]] as never

describe('GPS', () => {
  it('техника на связи: позиция, пробег, топливо, привязка и отвязка', async () => {
    const m = loggedIn(
      [
        ...(base() as []),
        ['GET', /^\/api\/gps\/units\//, { body: page([UNIT, FREE]) }],
        ['POST', '/api/gps/units/2/link/', { body: { ...FREE, vehicle: 8, vehicle_plate: '777BBB02' } }],
        ['POST', '/api/gps/units/1/unlink/', { body: { ...UNIT, vehicle: null, vehicle_plate: null } }],
      ],
      { session: MODULES },
    )
    renderApp('/gps?tab=units')
    expect(await screen.findByText('Volvo 886 AIA 14')).toBeInTheDocument()
    expect(screen.getByText(/123\s?456,7 км/)).toBeInTheDocument()
    expect(screen.getByText('310.5 л')).toBeInTheDocument()
    expect(screen.getByText('Алматы, пр. Аль-Фараби')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /43\.2389, 76\.9456/ })).toHaveAttribute('href', expect.stringContaining('openstreetmap.org'))
    await userEvent.selectOptions(screen.getByLabelText('Привязать к технике'), '8')
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/gps/units/2/link/')).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/gps/units/2/link/')?.body).toEqual({ vehicle: 8 })
    await userEvent.click(screen.getByRole('button', { name: 'Отвязать' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/gps/units/1/unlink/')).toBe(true) })
  })

  it('карта: позиции и зоны передаются на карту, трек запрашивается по кнопке за выбранный период', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/gps\/units\/\?/, { body: page([UNIT, FREE]) }],
        ['GET', /^\/api\/gps\/geofences\//, { body: page([GEO]) }],
        ['GET', /^\/api\/gps\/units\/1\/track\//, { body: { available: true, reason: '', total_points: 2, length_km: 12.3, points: [{ t: '2026-11-18T08:00:00Z', lat: 43.2, lon: 76.9, speed: 50 }, { t: '2026-11-18T09:00:00Z', lat: 43.3, lon: 77.0, speed: 60 }] } }],
      ],
      { session: MODULES },
    )
    renderApp('/gps')
    expect(await screen.findByTestId('map-stub')).toHaveTextContent('units=2 zones=1 track=0')
    await screen.findByRole('option', { name: /886AIA14/ })
    const show = screen.getByRole('button', { name: 'Показать трек' })
    expect(show).toBeDisabled() // юнит не выбран
    await userEvent.selectOptions(screen.getByLabelText('Юнит Wialon'), '1')
    await userEvent.click(show)
    expect(await screen.findByText('Точек в треке: 2, длина около 12.3 км')).toBeInTheDocument()
    expect(screen.getByTestId('map-stub')).toHaveTextContent('track=2')
    expect(m.calls.some((c) => /\/api\/gps\/units\/1\/track\/\?date_from=/.test(c.path))).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Убрать трек' }))
    await waitFor(() => { expect(screen.getByTestId('map-stub')).toHaveTextContent('track=0') })
  })

  it('карта: Wialon недоступен - понятное сообщение вместо трека', async () => {
    loggedIn(
      [
        ['GET', /^\/api\/gps\/units\/\?/, { body: page([UNIT]) }],
        ['GET', /^\/api\/gps\/geofences\//, { body: page([]) }],
        ['GET', /^\/api\/gps\/units\/1\/track\//, { body: { available: false, reason: 'wialon_error', total_points: 0, length_km: null, points: [] } }],
      ],
      { session: MODULES },
    )
    renderApp('/gps')
    await screen.findByRole('option', { name: /886AIA14/ })
    await userEvent.selectOptions(screen.getByLabelText('Юнит Wialon'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Показать трек' }))
    expect(await screen.findByText('Wialon недоступен, повторите позже')).toBeInTheDocument()
  })

  it('синхронизация и привязка по номеру вызывают сервер; без права управления кнопки отключены', async () => {
    const m = loggedIn(
      [
        ...(base() as []),
        ['GET', /^\/api\/gps\/units\//, { body: page([]) }],
        ['POST', '/api/gps/sync/', { body: { ok: true, units: { units_seen: 3, created: 3, updated: 0, auto_linked: 1 } } }],
      ],
      { session: MODULES },
    )
    renderApp('/gps?tab=units')
    await userEvent.click(await screen.findByRole('button', { name: 'Синхронизировать' }))
    expect(await screen.findByText('Синхронизировано юнитов: 3')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path === '/api/gps/sync/')).toBe(true)
  })

  it('наблюдатель без gps.manage: кнопки управления отключены, ссылки на настройки нет', async () => {
    loggedIn([...(base() as []), ['GET', /^\/api\/gps\/units\//, { body: page([UNIT]) }]], {
      session: { ...MODULES, permissions: ALL_PERMISSIONS.filter((p) => p !== 'gps.manage') },
    })
    renderApp('/gps?tab=units')
    expect(await screen.findByText('Volvo 886 AIA 14')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Синхронизировать' })).toBeDisabled()
    expect(screen.queryByRole('link', { name: 'Настройки GPS' })).not.toBeInTheDocument()
  })

  it('без модуля gps страницы нет', async () => {
    loggedIn([...(base() as [])], { session: makeSession({ modules: ['logistics', 'fleet'] }) })
    renderApp('/gps?tab=units')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })

  it('геозоны: список, новый контур разбирается из точек и уходит на сервер', async () => {
    const m = loggedIn(
      [
        ...(base() as []),
        ['GET', /^\/api\/gps\/geofences\//, { body: page([GEO]) }],
        ['POST', '/api/gps/geofences/', { status: 201, body: { ...GEO, id: 9 } }],
      ],
      { session: MODULES },
    )
    renderApp('/gps?tab=geofences')
    expect(await screen.findByText('Склад Алматы')).toBeInTheDocument()
    expect(screen.getByText('Круг 300 м')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Новая геозона/ }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Город')
    await userEvent.selectOptions(within(drawer).getByLabelText('Форма'), 'polygon')
    await userEvent.type(within(drawer).getByLabelText('Точки контура'), '43.0, 76.0{enter}43.0, 77.0{enter}44.0, 77.0')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/gps/geofences/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST' && c.path === '/api/gps/geofences/')?.body).toMatchObject({
      name: 'Город', shape: 'polygon', polygon: [[43, 76], [43, 77], [44, 77]],
    })
  })

  it('события: въезд и выезд с номером техники и названием зоны', async () => {
    loggedIn(
      [
        ['GET', /^\/api\/gps\/events\//, { body: page([{ id: 1, geofence: 3, geofence_name: 'Склад Алматы', vehicle: 7, vehicle_plate: '886AIA14', event_type: 'enter', occurred_at: '2026-11-18T08:00:00Z' }]) }],
      ],
      { session: MODULES },
    )
    renderApp('/gps?tab=events')
    expect(await screen.findByText('886AIA14')).toBeInTheDocument()
    expect(screen.getByText('Склад Алматы')).toBeInTheDocument()
    expect(screen.getAllByText('Въезд').length).toBeGreaterThan(0)
  })

  it('настройки GPS: токен не показывается, пустой токен при сохранении не уходит значением', async () => {
    const m = loggedIn(
      [
        ['GET', '/api/gps/account/', { body: { configured: true, has_token: true, base_url: 'https://hst-api.wialon.com', is_active: true, last_synced_at: null, last_sync_error: '', webhook_path: '/api/gps/wialon/webhook/10/abc/' } }],
        ['PUT', '/api/gps/account/', { body: { configured: true, has_token: true, base_url: 'https://hst-api.wialon.com', is_active: true } }],
        ['POST', '/api/gps/account/test/', { body: { ok: true, user: 'disp', units: 5 } }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/gps')
    expect(await screen.findByText(/Токен сохранён/)).toBeInTheDocument()
    expect(screen.getByText(/\/api\/gps\/wialon\/webhook\/10\/abc\//)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }))
    expect(await screen.findByText('Подключение работает, юнитов: 5')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ token: '' })
  })
})

describe('parsePolygon', () => {
  it('разбирает точки через запятую, точку с запятой и пробел; меньше трёх точек или мусор - null', () => {
    expect(parsePolygon('43.0, 76.0\n43.0;77.0\n44,5 77,5')).toBeNull() // «44,5 77,5» - четыре числа
    expect(parsePolygon('43.0, 76.0\n43.0 77.0\n44.0, 77.0')).toEqual([[43, 76], [43, 77], [44, 77]])
    expect(parsePolygon('43.0, 76.0\n43.0, 77.0')).toBeNull()
    expect(parsePolygon('a, b\nc, d\ne, f')).toBeNull()
    expect(parsePolygon('')).toBeNull()
  })
})
