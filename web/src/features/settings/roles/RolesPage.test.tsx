import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const roles = [
  { id: 1, name: 'Администратор', is_system: true, permissions: ALL_PERMISSIONS },
  { id: 9, name: 'Склад', is_system: false, permissions: ['trips.view'] },
]
const users = [
  { id: 1, user_id: 1, full_name: 'Админ', email: 'a@x.kz', phone: null, role: 1, role_name: 'Администратор', department: null, is_active: true },
  { id: 2, user_id: 2, full_name: 'Склад Складов', email: 's@x.kz', phone: null, role: 9, role_name: 'Склад', department: null, is_active: true },
]
const base: MockRoutes = [
  ['GET', '/api/roles/', { body: roles }],
  ['GET', '/api/users/', { body: users }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Роли и права', () => {
  it('список: системная метка и число сотрудников', async () => {
    loggedIn(base)
    renderApp('/settings/roles')
    const row = (await screen.findByRole('button', { name: 'Администратор' })).closest('tr')!
    expect(within(row).getByText('Системная')).toBeInTheDocument()
    const own = screen.getByRole('button', { name: 'Склад' }).closest('tr')!
    expect(within(own).getByText('Своя')).toBeInTheDocument()
    expect(within(own).getAllByRole('cell')[3]).toHaveTextContent('1')
  })

  it('системная роль открывается только для чтения с пояснением', async () => {
    loggedIn(base)
    renderApp('/settings/roles')
    await userEvent.click(await screen.findByRole('button', { name: 'Администратор' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Системная роль: её права менять нельзя/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/^Название/)).toBeDisabled()
    for (const box of within(dialog).getAllByRole('checkbox')) expect(box).toBeDisabled()
    expect(within(dialog).queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
  })

  it('права, которых нет у пользователя, отключены; создание шлёт выбранные коды', async () => {
    const m = loggedIn(
      [['POST', '/api/roles/', { status: 201, body: { id: 10, name: 'Новая', is_system: false, permissions: [] } }], ...base],
      { session: { permissions: ['roles.view', 'roles.create', 'trips.view', 'trips.update', 'clients.view'] } },
    )
    renderApp('/settings/roles')
    await userEvent.click(await screen.findByRole('button', { name: 'Новая роль' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('checkbox', { name: 'Корзина: Просмотр' })).toBeDisabled()
    expect(within(dialog).getByRole('checkbox', { name: 'Корзина: Просмотр' })).toHaveAttribute('title', 'У вас нет этого права, выдать его нельзя')
    expect(within(dialog).getByRole('checkbox', { name: 'Рейсы: Просмотр' })).toBeEnabled()
    await userEvent.type(within(dialog).getByLabelText(/^Название/), 'Новая')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Рейсы: Просмотр' }))
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Клиенты: Просмотр' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Новая', permissions: ['clients.view', 'trips.view'] }) })
  })

  it('матрица содержит 13 разделов x 4 действия', async () => {
    loggedIn(base)
    renderApp('/settings/roles')
    await userEvent.click(await screen.findByRole('button', { name: 'Новая роль' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(within(dialog).getByRole('table')).getAllByRole('checkbox')).toHaveLength(52)
    expect(within(dialog).getAllByRole('checkbox')).toHaveLength(60) // + особые права: финансы (2), выход рейса из «Завершён» и права финансовой архитектуры (5)
  })

  it('403 сервера при выдаче чужих прав показывается как есть', async () => {
    loggedIn([['POST', '/api/roles/', { status: 403, body: { detail: 'Нельзя выдать права, которых нет у вас самих: trash.view', code: 'permission_denied' } }], ...base])
    renderApp('/settings/roles')
    await userEvent.click(await screen.findByRole('button', { name: 'Новая роль' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Название/), 'Х')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText(/Нельзя выдать права, которых нет у вас самих/)).toBeInTheDocument()
  })

  it('удаление своей роли с подтверждением; 409 «роль назначена» показывается', async () => {
    const m = loggedIn([['DELETE', '/api/roles/9/', { status: 409, body: { detail: 'Роль назначена сотрудникам, сначала переназначьте их' } }], ...base])
    renderApp('/settings/roles')
    expect(screen.queryByRole('button', { name: 'Удалить роль Администратор' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить роль Склад' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    expect(await screen.findByText('Роль назначена сотрудникам, сначала переназначьте их')).toBeInTheDocument()
    expect(m.count('DELETE', '/api/roles/9/')).toBe(1)
  })

  it('в режиме только чтения «Новая роль» отключена; без roles.view - 403', async () => {
    loggedIn(base, { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/settings/roles')
    expect(await screen.findByRole('button', { name: 'Новая роль' })).toBeDisabled()
  })

  it('без roles.view прямой заход даёт 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'roles.view') } })
    renderApp('/settings/roles')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
