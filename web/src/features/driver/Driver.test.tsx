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

  it('вкладка «Отчёт» есть только при включённом распознавании', async () => {
    loggedIn([['GET', /^\/api\/driver\/trips\/\?/, { body: { results: [] } }]], { session: SESSION })
    renderApp('/driver')
    await screen.findByText('Сейчас вы не в рейсе')
    expect(screen.queryByRole('link', { name: 'Отчёт' })).not.toBeInTheDocument()
  })

  it('отчёт: типы из настроек компании, простая история с файлом, архив', async () => {
    const BASE = { engine: 'ocr_space', size: 1, has_file: true, text: '', fields: {}, sheet: {}, review: {}, error: '', uploaded_by_name: '', source: 'driver_app', trip: 4, trip_number: 'ORD-1-1', route: 'Алматы → Астана', driver: 1, driver_name: 'Иванов', vehicle: 2, vehicle_plate: '886AIA14', reviewed_at: null, archived_at: null, driver_archived_at: null, processed_at: null, status: 'done' }
    const REPORTS = [
      { ...BASE, id: 21, doc_type: 'report_sheet', doc_type_name: 'Рукописный отчётный лист', original_name: 's.jpg', created_at: '2026-11-21T08:00:00Z' },
      { ...BASE, id: 22, doc_type: 'fuel_receipt', doc_type_name: 'Чек АЗС', original_name: 'c.jpg', created_at: '2026-11-21T08:10:00Z' },
    ]
    const m = loggedIn(
      [
        ['GET', '/api/driver/report-types/', { body: { results: [{ code: 'report_sheet', name: 'Рукописный отчётный лист', handler: 'sheet' }, { code: 'fuel_receipt', name: 'Чек АЗС', handler: 'receipt' }] } }],
        ['POST', '/api/driver/reports/21/archive/', { body: { ...REPORTS[0], driver_archived_at: '2026-11-21T10:00:00Z' } }],
        ['GET', '/api/driver/reports/', { body: { results: REPORTS } }],
        ['GET', '/api/driver/reports/?archived=true', { body: { results: [] } }],
        ['POST', '/api/driver/reports/', { status: 201, body: REPORTS[0] }],
        ['GET', /^\/api\/driver\/trips\/\?scope=current/, { body: { results: [TRIP] } }],
        ['GET', /^\/api\/driver\/trips\/\?scope=upcoming/, { body: { results: [] } }],
      ],
      { session: { ...SESSION, modules: ['logistics', 'drivers', 'driver_app', 'ocr'] } },
    )
    renderApp('/driver/report')
    const cards = await screen.findAllByTestId('report-card')
    expect(cards).toHaveLength(2)
    expect(cards[0]).toHaveTextContent('Рукописный отчётный лист')
    expect(cards[0]).toHaveTextContent('Рейс ORD-1-1 · Алматы → Астана')
    expect(cards[0]).toHaveTextContent('Отправлено в офис')
    expect(screen.getAllByRole('button', { name: 'Смотреть файл' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Переснять (удалить)' })).not.toBeInTheDocument()
    // два способа добавить фото: камера и выбор файла из галереи (без capture)
    expect(screen.getByRole('button', { name: 'Сфотографировать' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Выбрать фото или файл' })).toBeInTheDocument()
    expect(screen.getByTestId('report-camera')).toHaveAttribute('capture', 'environment')
    expect(screen.getByTestId('report-file')).not.toHaveAttribute('capture')
    await userEvent.upload(screen.getByTestId('report-file'), new File(['x'], 'photo.jpg', { type: 'image/jpeg' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/driver/reports/')).toBe(true) })
    await userEvent.click(within(cards[0] as HTMLElement).getByRole('button', { name: 'Отправить в архив' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/driver/reports/21/archive/')?.body).toEqual({ archived: true }) })
    await userEvent.click(screen.getByRole('tab', { name: 'Архив' }))
    expect(await screen.findByText('Архив пуст')).toBeInTheDocument()
  })
})
