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
  error: '', uploaded_by_name: 'Админ', created_at: '2026-11-18T10:00:00Z', processed_at: '2026-11-18T10:00:01Z',
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
