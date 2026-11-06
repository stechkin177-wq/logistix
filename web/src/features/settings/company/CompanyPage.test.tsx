import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'
import { logoProblem } from './BrandingBlock'

const settings = { name: 'Альфа', timezone: 'Asia/Almaty', language: 'ru', accounting_start: null }
const branding = { app_name: 'Logistix', logo_url: null, primary_color: '#2563EB', theme: 'system' }
const sub = { plan: { code: 'start', name: 'Старт' }, status: 'active', is_free_period: true, ends_at: '2026-12-31T00:00:00Z', days_left: 30 }
const base: MockRoutes = [
  ['GET', '/api/company/settings/', { body: settings }],
  ['GET', '/api/company/branding/', { body: branding }],
  ['GET', '/api/billing/subscription/', { body: sub }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Настройки компании', () => {
  it('показывает данные и блок лицензии', async () => {
    loggedIn(base)
    renderApp('/settings/company')
    expect(await screen.findByDisplayValue('Альфа')).toBeInTheDocument()
    const license = (await screen.findByRole('heading', { name: 'Лицензия' })).closest('section')!
    expect(await within(license).findByText('Старт')).toBeInTheDocument()
    expect(within(license).getByText('Активна')).toBeInTheDocument()
    expect(within(license).getByText('30')).toBeInTheDocument()
    expect(within(license).getByText('Бесплатный период')).toBeInTheDocument()
  })

  it('ошибка часового пояса сервера ложится на поле', async () => {
    loggedIn([
      ['PATCH', '/api/company/settings/', { status: 400, body: { timezone: ['Неизвестный часовой пояс (IANA, например Asia/Almaty)'] } }],
      ...base,
    ])
    renderApp('/settings/company')
    const tz = await screen.findByLabelText('Часовой пояс')
    await userEvent.clear(tz)
    await userEvent.type(tz, 'Mars/Base')
    await userEvent.click(within(screen.getByLabelText(/^Название компании/).closest('form')!).getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText(/Неизвестный часовой пояс/)).toBeInTheDocument()
    expect(tz).toHaveAttribute('aria-invalid', 'true')
  })

  it('успешное сохранение: PATCH со всеми полями и обновление сессии', async () => {
    const m = loggedIn([['PATCH', '/api/company/settings/', { body: settings }], ...base])
    renderApp('/settings/company')
    await screen.findByDisplayValue('Альфа')
    await userEvent.click(within(screen.getByLabelText(/^Название компании/).closest('form')!).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ name: 'Альфа', timezone: 'Asia/Almaty', language: 'ru', accounting_start: null }) })
    await waitFor(() => { expect(m.count('GET', '/api/session/')).toBeGreaterThan(1) })
  })

  it('без company.update поля и кнопки сохранения отключены; без company.view - 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'company.update') } })
    renderApp('/settings/company')
    expect(await screen.findByLabelText(/^Название компании/)).toBeDisabled()
    for (const b of screen.getAllByRole('button', { name: 'Сохранить' })) expect(b).toBeDisabled()
  })

  it('без company.view прямой заход даёт 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'company.view') } })
    renderApp('/settings/company')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})

describe('Оформление', () => {
  const brandingForm = async () => {
    const m = loggedIn([['PATCH', '/api/company/branding/', { body: branding }], ...base])
    renderApp('/settings/company')
    await screen.findByLabelText('Название приложения')
    return m
  }
  const upload = (file: File) => {
    const input = screen.getByLabelText('Логотип')
    // в jsdom accept не отсекает файлы, как это делает браузер при выборе «любой файл»
    return userEvent.upload(input, file, { applyAccept: false })
  }
  const save = () => userEvent.click(within(screen.getByLabelText('Название приложения').closest('form')!).getByRole('button', { name: 'Сохранить' }))

  it('svg и файл больше 1 МБ отклоняются до запроса', async () => {
    const m = await brandingForm()
    await upload(new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' }))
    expect(await screen.findByText(/Допустимы только png, jpg, jpeg и webp/)).toBeInTheDocument()
    await save()
    await upload(new File([new Uint8Array(1024 * 1024 + 1)], 'big.png', { type: 'image/png' }))
    expect(await screen.findByText('Файл больше 1 МБ')).toBeInTheDocument()
    await save()
    expect(m.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('logoProblem: допустимые и недопустимые файлы', () => {
    expect(logoProblem(new File(['x'], 'a.PNG'))).toBeNull()
    expect(logoProblem(new File(['x'], 'a.webp'))).toBeNull()
    expect(logoProblem(new File(['x'], 'a.gif'))).toBe('badType')
    expect(logoProblem(new File([], 'a.png'))).toBe('empty')
  })

  it('цвет проверяется как #RRGGBB, запроса с плохим цветом нет', async () => {
    const m = await brandingForm()
    const color = screen.getByLabelText('Основной цвет')
    await userEvent.clear(color)
    await userEvent.type(color, '#12345')
    await save()
    expect(await screen.findByText('Цвет задаётся как #RRGGBB')).toBeInTheDocument()
    expect(color).toHaveAttribute('aria-invalid', 'true')
    expect(m.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('предпросмотр цвета обновляет и читаемый цвет текста (--brand-fg)', async () => {
    await brandingForm()
    const color = screen.getByLabelText('Основной цвет')
    await userEvent.clear(color)
    await userEvent.type(color, '#FFFF00')
    expect(document.documentElement.style.getPropertyValue('--brand-fg')).toBe('#020617')
    await userEvent.clear(color)
    await userEvent.type(color, '#2563EB')
    expect(document.documentElement.style.getPropertyValue('--brand-fg')).toBe('#ffffff')
  })

  it('предпросмотр применяется сразу, сохранение шлёт multipart и обновляет сессию', async () => {
    const m = await brandingForm()
    const color = screen.getByLabelText('Основной цвет')
    await userEvent.clear(color)
    await userEvent.type(color, '#FF0000')
    expect(document.documentElement.style.getPropertyValue('--brand-500')).toBe('#FF0000')
    await upload(new File([new Uint8Array([137, 80, 78, 71])], 'logo.png', { type: 'image/png' }))
    await save()
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const form = m.calls.find((c) => c.method === 'PATCH')!.body as FormData
    expect(form.get('primary_color')).toBe('#FF0000')
    expect(form.get('theme')).toBe('system')
    expect((form.get('logo') as File).name).toBe('logo.png')
    await waitFor(() => { expect(m.count('GET', '/api/session/')).toBeGreaterThan(1) })
  })

  it('«Убрать логотип» отправляет пустое значение logo', async () => {
    const m = loggedIn([
      ['PATCH', '/api/company/branding/', { body: branding }],
      ['GET', '/api/company/branding/', { body: { ...branding, logo_url: '/media/branding/x/y.png' } }],
      ...base,
    ])
    renderApp('/settings/company')
    await userEvent.click(await screen.findByRole('button', { name: 'Убрать логотип' }))
    await save()
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    expect((m.calls.find((c) => c.method === 'PATCH')!.body as FormData).get('logo')).toBe('')
  })
})
