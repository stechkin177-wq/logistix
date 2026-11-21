import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import { shrinkImage } from './image'

const MODULES = { modules: ['documents', 'ocr'] }
const TYPES = [
  { id: 1, code: 'fuel_receipt', name: 'Чек АЗС', handler: 'receipt', driver_visible: true, is_active: true, sort_order: 10, used: 1 },
  { id: 2, code: 'report_sheet', name: 'Рукописный отчётный лист', handler: 'sheet', driver_visible: true, is_active: true, sort_order: 20, used: 0 },
  { id: 3, code: 'other', name: 'Другое', handler: 'generic', driver_visible: true, is_active: true, sort_order: 30, used: 0 },
]
const TYPES_ROUTE: ['GET', string, { body: unknown }] = ['GET', '/api/ocr/doc-types/', { body: TYPES }]
const DOC = {
  id: 5, doc_type: 'fuel_receipt', doc_type_name: 'Чек АЗС', vehicle: null, vehicle_plate: '', route: '', review: {}, archived_at: null, driver_archived_at: null, status: 'done', engine: 'ocr_space', original_name: 'check.jpg', size: 1000, has_file: true,
  text: 'ИТОГО 37355,00', fields: { date: '2026-11-18', amount: '37355', liters: '120.5', fuel_type: 'diesel', plate: '886AIA14' },
  error: '', uploaded_by_name: 'Админ', source: 'office', trip: null, trip_number: '', driver: null, driver_name: '', reviewed_at: null, created_at: '2026-11-18T10:00:00Z', processed_at: '2026-11-18T10:00:01Z',
}
const SETTINGS = {
  engine: 'ocr_space', auto_fallback: true, has_google_vision_key: false, has_ocr_space_key: true, tesseract_available: false, storage_configured: false,
  has_gemini_key: true, handwriting_enabled: true, handwriting_crosscheck: false, handwriting_model: 'gemini-3.5-flash-lite', handwriting_check_model: '', google_used: 0, google_limit: 900,
  engines: [{ code: 'gemini', label: 'Google Gemini' }, { code: 'ocr_space', label: 'OCR.space' }, { code: 'google_vision', label: 'Google Cloud Vision' }, { code: 'tesseract', label: 'Tesseract' }],
}

describe('Распознавание документов', () => {
  it('список и правка найденных полей в карточке', async () => {
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', /^\/api\/ocr\/documents\//, { body: page([DOC]) }],
        ['PATCH', '/api/ocr/documents/5/', { body: DOC }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr?by=all')
    await userEvent.click(await screen.findByRole('button', { name: 'Чек АЗС' }))
    const liters = await screen.findByLabelText('Литры')
    expect(liters).toHaveValue('120.5')
    expect(screen.getByLabelText('Вид топлива')).toHaveValue('diesel')
    await userEvent.clear(liters)
    await userEvent.type(liters, '100')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'PATCH')?.body as { fields: Record<string, string>; doc_type: string }
    expect(body.doc_type).toBe('fuel_receipt')
    expect(body.fields.liters).toBe('100')
  })

  it('загрузка файла отправляет multipart с типом документа', async () => {
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', /^\/api\/ocr\/documents\//, { body: page([]) }],
        ['POST', '/api/ocr/documents/', { status: 201, body: DOC }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr?by=all')
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument()
    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' })
    await userEvent.upload(screen.getByTestId('ocr-file'), file)
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/ocr/documents/')).toBe(true) })
  })

  it('настройки: ключи не показываются, сохранение отправляет выбранный движок', async () => {
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', '/api/ocr/settings/', { body: SETTINGS }],
        ['PUT', '/api/ocr/settings/', { body: SETTINGS }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/ocr')
    expect((await screen.findAllByText('Ключ сохранён. Оставьте пустым, чтобы не менять.')).length).toBeGreaterThan(0)
    await userEvent.selectOptions(screen.getByLabelText('Основной движок'), 'google_vision')
    await userEvent.type(screen.getByLabelText('Ключ Google Cloud Vision'), 'GV-1')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ engine: 'google_vision', google_vision_key: 'GV-1', ocr_space_key: '' })
  })

  it('малое фото идёт без пережатия', async () => {
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const out = await shrinkImage(file)
    expect(out.blob).toBe(file)
    expect(out.name).toBe('a.png')
  })
})

describe('Рукописный лист', () => {
  const SHEET_DOC = {
    ...DOC,
    id: 9, doc_type: 'report_sheet', doc_type_name: 'Рукописный отчётный лист', engine: 'gemini', original_name: 'sheet.jpg', fields: {}, text: '',
    sheet: {
      page_type: 'main', models: ['gemini-3.7-flash', 'gemini-3.5-flash'], notes: ['Проверьте строки с фото'],
      raw: { header: { driver: 'Иванов', end_odometer_km: '104500' }, fuel_tractor: [{ liters: '120', price: '310', amount: '40000' }] },
      flags: { 'fuel_tractor[0].liters': ['Литры x цена = 37200, а сумма 40000'] },
      alt: { 'fuel_tractor[0].liters': '126' },
    },
  }

  it('карточка показывает прочитанное, подсвечивает сомнительное и расхождение второго чтения', async () => {
    loggedIn([TYPES_ROUTE, ['GET', /^\/api\/ocr\/documents\//, { body: page([SHEET_DOC]) }]], { session: MODULES })
    renderApp('/ocr?by=all')
    await userEvent.click(await screen.findByRole('button', { name: 'Рукописный отчётный лист' }))
    const view = await screen.findByTestId('sheet-view')
    expect(view).toHaveTextContent('Иванов')
    expect(view).toHaveTextContent('Литры x цена = 37200, а сумма 40000')
    expect(view).toHaveTextContent('второе чтение: 126')
    expect(view).toHaveTextContent('Проверьте строки с фото')
    expect(view.querySelectorAll('[data-flagged="true"]')).toHaveLength(1)
    expect(screen.queryByLabelText('Литры')).not.toBeInTheDocument() // полей чека у листа нет
  })

  it('настройки: Gemini в списке движков, одна модель, лишних кнопок нет', async () => {
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', '/api/ocr/settings/', { body: SETTINGS }],
        ['PUT', '/api/ocr/settings/', { body: SETTINGS }],
        ['POST', '/api/ocr/settings/test/', { body: { results: { gemini: { ok: true, error: '' }, ocr_space: { ok: false, error: 'нет ключа' } } } }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/ocr')
    const engine = await screen.findByLabelText('Основной движок')
    expect(within(engine).getByRole('option', { name: 'Google Gemini' })).toBeInTheDocument()
    for (const gone of ['Проверить Gemini', 'Показать доступные модели', 'Проверить все доступные']) expect(screen.queryByRole('button', { name: gone })).not.toBeInTheDocument()
    await userEvent.selectOptions(engine, 'gemini')
    await userEvent.click(screen.getByRole('button', { name: 'Проверить движки' }))
    expect(await screen.findByText('Google Gemini: работает')).toBeInTheDocument()
    expect(screen.getByText('OCR.space: нет ключа')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Ключ Gemini'), 'AIza-1')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ engine: 'gemini', gemini_key: 'AIza-1', handwriting_model: 'gemini-3.5-flash-lite', handwriting_crosscheck: false })
  })

  it('настройки: типы документов добавляются и отключаются для водителя', async () => {
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', '/api/ocr/settings/', { body: SETTINGS }],
        ['POST', '/api/ocr/doc-types/', { status: 201, body: { ...TYPES[2], id: 9, code: 't1', name: 'Акт' } }],
        ['PATCH', '/api/ocr/doc-types/3/', { body: TYPES[2] }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/ocr')
    await userEvent.type(await screen.findByLabelText('Новый тип документа'), 'Акт')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить тип' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST' && c.path === '/api/ocr/doc-types/')?.body).toEqual({ name: 'Акт', handler: 'generic', driver_visible: true }) })
    const rows = await screen.findAllByTestId('doctype-row')
    await userEvent.click(within(rows[2] as HTMLElement).getByLabelText('Показывать водителю'))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ driver_visible: false }) })
  })

  it('документ водителя: рейс и водитель в списке, офис отмечает проверенным', async () => {
    const FROM_DRIVER = { ...DOC, id: 31, original_name: 'driver.jpg', source: 'driver_app', trip: 4, trip_number: 'ORD-1-1', driver: 1, driver_name: 'Иванов Иван' }
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', /^\/api\/ocr\/documents\//, { body: page([FROM_DRIVER]) }],
        ['POST', '/api/ocr/documents/31/review/', { body: { ...FROM_DRIVER, reviewed_at: '2026-11-21T09:00:00Z' } }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr?by=all')
    expect(await screen.findByText('ORD-1-1')).toBeInTheDocument()
    expect(screen.getByText('На проверке')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Чек АЗС' }))
    expect(await screen.findByText('Отправил водитель Иванов Иван, рейс ORD-1-1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отметить проверенным' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/ocr/documents/31/review/')?.body).toEqual({ reviewed: true }) })
  })

  it('разделение по водителям: список групп, документы выбранного водителя, вкладка «Архив»', async () => {
    const GROUPS = { results: [{ id: 1, name: 'Иванов Иван', total: 2, pending: 1 }, { id: 0, name: '', total: 1, pending: 0 }] }
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', /^\/api\/ocr\/documents\/groups\//, { body: GROUPS }],
        ['GET', /^\/api\/ocr\/documents\//, { body: page([{ ...DOC, id: 41, source: 'driver_app', driver: 1, driver_name: 'Иванов Иван', route: 'Алматы → Астана', trip_number: 'ORD-7-1', vehicle_plate: '886AIA14' }]) }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr')
    const groups = await screen.findByTestId('ocr-groups')
    expect(await within(groups).findByText('Иванов Иван')).toBeInTheDocument()
    expect(within(groups).getByText('Без водителя')).toBeInTheDocument()
    expect(await screen.findByText('Алматы → Астана')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path.startsWith('/api/ocr/documents/?') && c.path.includes('driver=1'))).toBe(true)
    await userEvent.click(screen.getByRole('tab', { name: /Архив/ }))
    await waitFor(() => { expect(m.calls.some((c) => c.path.startsWith('/api/ocr/documents/?') && c.path.includes('archived=true'))).toBe(true) })
    expect(await screen.findByText(/фото удаляются через 180 дней/)).toBeInTheDocument()
  })

  it('«Сверить с фото»: сомнительное сверху, подтверждение и правка сохраняются', async () => {
    const SHEET_DOC = {
      ...DOC, id: 9, doc_type: 'report_sheet', doc_type_name: 'Рукописный отчётный лист', engine: 'gemini', original_name: 'sheet.jpg', fields: {}, text: '',
      sheet: {
        page_type: 'main', models: ['gemini-3.5-flash-lite'], notes: [],
        raw: { header: { driver: 'Иванов' }, cash_received: [{ amount: '2000+200' }], fuel_tractor: [{ liters: '120', amount: '40000' }] },
        flags: { 'fuel_tractor[0].liters': ['Литры x цена = 37200, а сумма 40000'] }, alt: {},
      },
    }
    const m = loggedIn(
      [
        TYPES_ROUTE,
        ['GET', '/api/ocr/documents/9/image/', { body: 'x' }],
        ['GET', /^\/api\/ocr\/documents\//, { body: page([SHEET_DOC]) }],
        ['POST', '/api/ocr/documents/9/save-review/', { body: SHEET_DOC }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr?by=all')
    await userEvent.click(await screen.findByRole('button', { name: 'Рукописный отчётный лист' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Сверить с фото' }))
    const dialog = await screen.findByRole('dialog', { name: /Сверка с фото/ })
    const review = within(dialog)
    const done = review.getByRole('button', { name: 'Готово, проверено' })
    expect(done).toBeDisabled() // пока сомнительное не подтверждено
    expect(review.getByText('2000 + 200 = 2200')).toBeInTheDocument()
    expect(review.getByText('Осталось проверить: 1 из 1')).toBeInTheDocument()
    await userEvent.click(review.getByRole('button', { name: 'Верно' }))
    await waitFor(() => { expect(done).toBeEnabled() })
    const cash = review.getAllByLabelText('[0].amount')[0] as HTMLElement
    await userEvent.clear(cash)
    await userEvent.type(cash, '2500')
    await userEvent.click(done)
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/ocr/documents/9/save-review/')?.body).toEqual({ edits: { 'cash_received[0].amount': '2500' }, checked: ['fuel_tractor[0].liters'], done: true }) })
  })
})
