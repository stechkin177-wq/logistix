import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { BRANDING } from '../../test/fixtures'
import { renderApp } from '../../test/renderApp'

const brand: Parameters<typeof mockFetch>[0][number] = ['GET', /^\/api\/branding\//, { body: BRANDING }]

describe('Установка пароля по одноразовой ссылке', () => {
  it('человек сам задаёт пароль: отправляются uid, токен и пароль, затем ссылка на вход', async () => {
    const m = mockFetch([brand, ['POST', '/api/auth/password-setup/', { status: 204 }]])
    renderApp('/setup-password?uid=MQ&token=abc-123')
    await userEvent.type(await screen.findByLabelText('Новый пароль'), 'Brand-new-pass-42')
    await userEvent.type(screen.getByLabelText('Повторите новый пароль'), 'Brand-new-pass-42')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить пароль' }))
    await waitFor(() => { expect(m.calls.find((c) => c.path === '/api/auth/password-setup/')?.body).toEqual({ uid: 'MQ', token: 'abc-123', new_password: 'Brand-new-pass-42' }) })
    expect(await screen.findByText('Пароль установлен. Теперь войдите.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Перейти ко входу' })).toHaveAttribute('href', '/login')
  })

  it('несовпадение паролей - запроса нет; недействительная ссылка - сообщение сервера', async () => {
    const m = mockFetch([brand, ['POST', '/api/auth/password-setup/', { status: 400, body: { token: ['Ссылка недействительна или устарела'] } }]])
    renderApp('/setup-password?uid=MQ&token=old')
    await userEvent.type(await screen.findByLabelText('Новый пароль'), 'Brand-new-pass-42')
    await userEvent.type(screen.getByLabelText('Повторите новый пароль'), 'другой')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить пароль' }))
    expect(await screen.findByText('Пароли не совпадают')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path === '/api/auth/password-setup/')).toBe(false)
    await userEvent.clear(screen.getByLabelText('Повторите новый пароль'))
    await userEvent.type(screen.getByLabelText('Повторите новый пароль'), 'Brand-new-pass-42')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить пароль' }))
    expect(await screen.findByText('Ссылка недействительна или устарела')).toBeInTheDocument()
  })

  it('без uid/token форма не показывается', async () => {
    mockFetch([brand])
    renderApp('/setup-password')
    expect(await screen.findByText('Ссылка неполная. Запросите новую у администратора.')).toBeInTheDocument()
  })
})
