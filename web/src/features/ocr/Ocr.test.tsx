import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import { shrinkImage } from './image'

const MODULES = { modules: ['documents', 'ocr'] }
const DOC = {
  id: 5, doc_type: 'fuel_receipt', status: 'done', engine: 'ocr_space', original_name: 'check.jpg', size: 1000, has_file: false,
  text: 'ИТОГО 37355,00', fields: { date: '2026-11-18', amount: '37355', liters: '120.5', fuel_type: 'diesel', plate: '886AIA14' },
  error: '', uploaded_by_name: 'Админ', source: 'office', trip: null, trip_number: '', driver: null, driver_name: '', reviewed_at: null, created_at: '2026-11-18T10:00:00Z', processed_at: '2026-11-18T10:00:01Z',
}
const SETTINGS = {
  engine: 'ocr_space', auto_fallback: true, has_google_vision_key: false, has_ocr_space_key: true, tesseract_available: false, storage_configured: false,
  engines: [{ code: 'google_vision', label: 'Google Cloud Vision' }, { code: 'ocr_space', label: 'OCR.space' }, { code: 'tesseract', label: 'Tesseract' }],
}

describe('Распознавание документов', () => {
  it('список и правка найденных полей в карточке', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/ocr\/documents\//, { body: page([DOC]) }],
        ['PATCH', '/api/ocr/documents/5/', { body: DOC }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr')
    await userEvent.click(await screen.findByRole('button', { name: 'check.jpg' }))
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
        ['GET', /^\/api\/ocr\/documents\//, { body: page([]) }],
        ['POST', '/api/ocr/documents/', { status: 201, body: DOC }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr')
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument()
    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' })
    await userEvent.upload(screen.getByTestId('ocr-file'), file)
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/ocr/documents/')).toBe(true) })
  })

  it('настройки: ключи не показываются, сохранение отправляет выбранный движок', async () => {
    const m = loggedIn(
      [
        ['GET', '/api/ocr/settings/', { body: SETTINGS }],
        ['PUT', '/api/ocr/settings/', { body: SETTINGS }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/ocr')
    expect(await screen.findByText('Ключ сохранён. Оставьте пустым, чтобы не менять.')).toBeInTheDocument()
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
    id: 9, doc_type: 'report_sheet', engine: 'gemini', original_name: 'sheet.jpg', fields: {}, text: '',
    sheet: {
      page_type: 'main', models: ['gemini-3.7-flash', 'gemini-3.5-flash'], notes: ['Проверьте строки с фото'],
      raw: { header: { driver: 'Иванов', end_odometer_km: '104500' }, fuel_tractor: [{ liters: '120', price: '310', amount: '40000' }] },
      flags: { 'fuel_tractor[0].liters': ['Литры x цена = 37200, а сумма 40000'] },
      alt: { 'fuel_tractor[0].liters': '126' },
    },
  }

  it('карточка показывает прочитанное, подсвечивает сомнительное и расхождение второго чтения', async () => {
    loggedIn([['GET', /^\/api\/ocr\/documents\//, { body: page([SHEET_DOC]) }]], { session: MODULES })
    renderApp('/ocr')
    await userEvent.click(await screen.findByRole('button', { name: 'sheet.jpg' }))
    const view = await screen.findByTestId('sheet-view')
    expect(view).toHaveTextContent('Иванов')
    expect(view).toHaveTextContent('Литры x цена = 37200, а сумма 40000')
    expect(view).toHaveTextContent('второе чтение: 126')
    expect(view).toHaveTextContent('Проверьте строки с фото')
    expect(view.querySelectorAll('[data-flagged="true"]')).toHaveLength(1)
    expect(screen.queryByLabelText('Литры')).not.toBeInTheDocument() // полей чека у листа нет
  })

  it('настройки: проверка Gemini и сохранение ключа и моделей', async () => {
    const m = loggedIn(
      [
        ['GET', '/api/ocr/settings/', { body: { ...SETTINGS, has_gemini_key: true, handwriting_enabled: true, handwriting_crosscheck: true, handwriting_model: 'gemini-3.7-flash', handwriting_check_model: 'gemini-3.5-flash' } }],
        ['PUT', '/api/ocr/settings/', { body: SETTINGS }],
        ['POST', '/api/ocr/settings/test-gemini/', { body: { ok: false, models: { 'gemini-3.7-flash': { ok: true, error: '' }, 'gemini-3.5-flash': { ok: false, error: 'модель недоступна' } } } }],
      ],
      { session: MODULES },
    )
    renderApp('/settings/ocr')
    await userEvent.click(await screen.findByRole('button', { name: 'Проверить Gemini' }))
    expect(await screen.findByText('gemini-3.7-flash: работает')).toBeInTheDocument()
    expect(screen.getByText('gemini-3.5-flash: модель недоступна')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Ключ Gemini'), 'AIza-1')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ gemini_key: 'AIza-1', handwriting_model: 'gemini-3.7-flash', handwriting_crosscheck: true })
  })

  it('документ водителя: рейс и водитель в списке, офис отмечает проверенным', async () => {
    const FROM_DRIVER = { ...DOC, id: 31, original_name: 'driver.jpg', source: 'driver_app', trip: 4, trip_number: 'ORD-1-1', driver: 1, driver_name: 'Иванов Иван' }
    const m = loggedIn(
      [
        ['GET', /^\/api\/ocr\/documents\//, { body: page([FROM_DRIVER]) }],
        ['POST', '/api/ocr/documents/31/review/', { body: { ...FROM_DRIVER, reviewed_at: '2026-11-21T09:00:00Z' } }],
      ],
      { session: MODULES },
    )
    renderApp('/ocr')
    expect(await screen.findByText('ORD-1-1')).toBeInTheDocument()
    expect(screen.getByText('На проверке')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'driver.jpg' }))
    expect(await screen.findByText('Отправил водитель Иванов Иван, рейс ORD-1-1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отметить проверенным' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/ocr/documents/31/review/')?.body).toEqual({ reviewed: true }) })
  })
})
