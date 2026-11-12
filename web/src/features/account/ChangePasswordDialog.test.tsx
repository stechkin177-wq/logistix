import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { getAccess } from '../../shared/auth/tokens'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const open = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Меню профиля' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Сменить пароль' }))
  return screen.findByRole('dialog')
}
const fill = async (dialog: HTMLElement, old: string, next: string, confirm = next) => {
  await userEvent.type(within(dialog).getByLabelText(/^Текущий пароль/), old)
  await userEvent.type(within(dialog).getByLabelText(/^Новый пароль/), next)
  await userEvent.type(within(dialog).getByLabelText(/^Повторите новый пароль/), confirm)
}
const save = (dialog: HTMLElement) => userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))

describe('Смена пароля', () => {
  it('поля с метками и подходящими autocomplete', async () => {
    loggedIn()
    renderApp('/')
    const dialog = await open()
    expect(within(dialog).getByLabelText(/^Текущий пароль/)).toHaveAttribute('autocomplete', 'current-password')
    expect(within(dialog).getByLabelText(/^Новый пароль/)).toHaveAttribute('autocomplete', 'new-password')
    expect(within(dialog).getByLabelText(/^Повторите новый пароль/)).toHaveAttribute('autocomplete', 'new-password')
    for (const label of [/^Текущий пароль/, /^Новый пароль/, /^Повторите новый пароль/]) {
      expect(within(dialog).getByLabelText(label)).toHaveAttribute('type', 'password')
    }
  })

  it('успех: POST с двумя паролями, окно закрыто, показан тост', async () => {
    const m = loggedIn([['POST', '/api/auth/password/', { body: { access: 'new-a', refresh: 'new-r' } }]])
    renderApp('/')
    const dialog = await open()
    await fill(dialog, 'old-password-1', 'Brand-new-pass-42')
    await save(dialog)
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    expect(m.calls.find((c) => c.path === '/api/auth/password/')?.body).toEqual({ old_password: 'old-password-1', new_password: 'Brand-new-pass-42' })
    expect(await screen.findByText('Пароль изменён')).toBeInTheDocument()
    expect(getAccess()).toBe('new-a') // прежние токены отозваны сервером, сессия продолжается на новых
  })

  it('неверный текущий пароль ложится на поле', async () => {
    loggedIn([['POST', '/api/auth/password/', { status: 400, body: { old_password: ['Неверный текущий пароль'] } }]])
    renderApp('/')
    const dialog = await open()
    await fill(dialog, 'nope', 'Brand-new-pass-42')
    await save(dialog)
    expect(await within(dialog).findByText('Неверный текущий пароль')).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/^Текущий пароль/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('слабый новый пароль: ошибка сервера у поля нового пароля', async () => {
    loggedIn([['POST', '/api/auth/password/', { status: 400, body: { new_password: ['Этот пароль слишком широко распространён.'] } }]])
    renderApp('/')
    const dialog = await open()
    await fill(dialog, 'old-password-1', 'password')
    await save(dialog)
    expect(await within(dialog).findByText(/слишком широко распространён/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/^Новый пароль/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('несовпадение подтверждения и совпадение со старым ловятся без запроса', async () => {
    const m = loggedIn([['POST', '/api/auth/password/', { body: { access: 'new-a', refresh: 'new-r' } }]])
    renderApp('/')
    const dialog = await open()
    await fill(dialog, 'old-password-1', 'Brand-new-pass-42', 'other')
    await save(dialog)
    expect(await within(dialog).findByText('Пароли не совпадают')).toBeInTheDocument()
    await userEvent.clear(within(dialog).getByLabelText(/^Новый пароль/))
    await userEvent.type(within(dialog).getByLabelText(/^Новый пароль/), 'old-password-1')
    await save(dialog)
    expect(await within(dialog).findByText('Новый пароль должен отличаться от текущего')).toBeInTheDocument()
    expect(m.calls.find((c) => c.path === '/api/auth/password/')).toBeUndefined()
  })

  it('пароли не попадают в хранилище и URL, поля пусты при повторном открытии', async () => {
    const m = loggedIn([['POST', '/api/auth/password/', { body: { access: 'new-a', refresh: 'new-r' } }]])
    const { router } = renderApp('/')
    let dialog = await open()
    await fill(dialog, 'old-password-1', 'Brand-new-pass-42')
    await save(dialog)
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    expect(m.calls.length).toBeGreaterThan(0)
    const dump = JSON.stringify(Object.entries(window.localStorage)) + JSON.stringify(Object.entries(window.sessionStorage)) + router.state.location.search + router.state.location.pathname
    expect(dump).not.toContain('old-password-1')
    expect(dump).not.toContain('Brand-new-pass-42')
    dialog = await open()
    expect(within(dialog).getByLabelText(/^Текущий пароль/)).toHaveValue('')
    expect(within(dialog).getByLabelText(/^Новый пароль/)).toHaveValue('')
  })
})
