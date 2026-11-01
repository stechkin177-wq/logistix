import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const base: MockRoutes = [
  ['GET', '/api/roles/', { body: [{ id: 1, name: 'Администратор', is_system: true, permissions: ALL_PERMISSIONS }] }],
  ['GET', '/api/users/', { body: [] }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Роли: особые права финансов', () => {
  it('особые права выставляются в роли и уходят на сервер', async () => {
    const m = loggedIn([['POST', '/api/roles/', { status: 201, body: { id: 10, name: 'Бухгалтер-2', is_system: false, permissions: [] } }], ...base])
    const user = userEvent.setup()
    renderApp('/settings/roles')
    await user.click(await screen.findByRole('button', { name: 'Новая роль' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/^Название/), 'Бухгалтер-2')
    await user.click(within(dialog).getByLabelText('Финансы: отменять выставленные счета'))
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Бухгалтер-2', permissions: ['finance.cancel_invoice'] })
    })
  })

  it('если права нет у самого пользователя, его нельзя выдать', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.override_limit') } })
    const user = userEvent.setup()
    renderApp('/settings/roles')
    await user.click(await screen.findByRole('button', { name: 'Новая роль' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Финансы: выставлять счёт сверх кредитного лимита')).toBeDisabled()
    expect(within(dialog).getByLabelText('Финансы: отменять выставленные счета')).toBeEnabled()
  })

  it('системная роль показывает особые права только для чтения', async () => {
    loggedIn(base)
    renderApp('/settings/roles')
    await userEvent.click(await screen.findByRole('button', { name: 'Администратор' }))
    const dialog = await screen.findByRole('dialog')
    const box = within(dialog).getByLabelText('Финансы: отменять выставленные счета')
    expect(box).toBeChecked()
    expect(box).toBeDisabled()
  })
})
