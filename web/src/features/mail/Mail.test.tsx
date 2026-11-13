import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const SENT = {
  id: 1, to: ['a@client.kz'], cc: [], subject: 'Счёт по заказу', body: '', state: 'sent', error: '', sent_at: '2026-11-13T10:00:00Z', attempts: 1,
  order: null, order_number: null, trip: null, trip_number: null, client: null, client_name: null, created_by_name: 'Мария', created_at: '2026-11-13T10:00:00Z', attachments: [],
}
const FAILED = { ...SENT, id: 2, subject: 'Не ушло', state: 'failed', error: 'SMTPAuthenticationError: bad credentials', sent_at: null }

describe('Почта', () => {
  it('список писем: статусы, ошибка отправки и повторная отправка', async () => {
    const m = loggedIn([
      ['GET', '/api/mail/status/', { body: { configured: true, from_email: 'o@c.kz' } }],
      ['GET', /^\/api\/mail\/messages\//, { body: page([SENT, FAILED]) }],
      ['POST', '/api/mail/messages/2/send/', { body: { ...FAILED, state: 'sent', error: '' } }],
    ])
    renderApp('/mail')
    expect(await screen.findByText('Счёт по заказу')).toBeInTheDocument()
    expect(screen.getByText('SMTPAuthenticationError: bad credentials')).toBeInTheDocument()
    expect(screen.getAllByText('Отправлено').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Отправить повторно: Не ушло' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/mail/messages/2/send/')).toBe(true) })
  })

  it('новое письмо: получатели разбираются по запятой и уходят с send=true', async () => {
    const m = loggedIn([
      ['GET', '/api/mail/status/', { body: { configured: true, from_email: 'o@c.kz' } }],
      ['GET', /^\/api\/mail\/messages\//, { body: page([]) }],
      ['GET', '/api/mail/templates/', { body: [] }],
      ['POST', '/api/mail/messages/', { status: 201, body: SENT }],
    ])
    renderApp('/mail')
    await userEvent.click(await screen.findByRole('button', { name: 'Написать письмо' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Кому/), 'a@b.kz, c@d.kz')
    await userEvent.type(within(dialog).getByLabelText(/Тема/), 'Привет')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/mail/messages/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')?.body).toMatchObject({ to: ['a@b.kz', 'c@d.kz'], subject: 'Привет', send: true })
  })

  it('ящик не настроен: кнопка отключена, видно предупреждение', async () => {
    loggedIn([
      ['GET', '/api/mail/status/', { body: { configured: false, from_email: '' } }],
      ['GET', /^\/api\/mail\/messages\//, { body: page([]) }],
    ])
    renderApp('/mail')
    expect(await screen.findByText(/Почта не настроена/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Написать письмо' })).toBeDisabled()
  })

  it('настройки: пароль не показывается, пустой пароль уходит пустым, сохранение PUT', async () => {
    const m = loggedIn([
      ['GET', '/api/mail/account/', { body: { configured: true, host: 'smtp.c.kz', port: 587, security: 'starttls', username: 'u', has_password: true, from_email: 'o@c.kz', from_name: '', is_active: true } }],
      ['GET', '/api/mail/templates/', { body: [{ id: 1, name: 'Счёт', subject: 'Заказ', body: '' }] }],
      ['PUT', '/api/mail/account/', { body: { configured: true } }],
    ])
    renderApp('/settings/mail')
    expect(await screen.findByDisplayValue('smtp.c.kz')).toBeInTheDocument()
    expect(screen.getByText(/Пароль сохранён/)).toBeInTheDocument()
    expect((screen.getByLabelText<HTMLInputElement>('Пароль')).value).toBe('')
    expect(screen.getByText('Счёт')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PUT' && c.path === '/api/mail/account/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PUT')!.body).toMatchObject({ host: 'smtp.c.kz', password: '' })
  })

  it('без mail.view раздел недоступен', async () => {
    loggedIn([['GET', /^\/api\/mail\/messages\//, { body: page([]) }]], { session: { permissions: ALL_PERMISSIONS.filter((p) => !p.startsWith('mail.')) } })
    renderApp('/mail')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(screen.queryByRole('heading', { name: 'Почта' })).not.toBeInTheDocument()
  })
})
