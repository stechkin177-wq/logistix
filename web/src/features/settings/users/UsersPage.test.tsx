import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const users = [
  { id: 1, user_id: 1, full_name: 'Админ Админов', email: 'a@x.kz', phone: null, role: 1, role_name: 'Администратор', department: null, is_active: true },
  { id: 2, user_id: 2, full_name: 'Мария', email: 'm@x.kz', phone: null, role: 2, role_name: 'Менеджер', department: 4, is_active: true },
]
const base: MockRoutes = [
  ['GET', '/api/users/', { body: users }],
  ['GET', '/api/roles/', { body: [{ id: 1, name: 'Администратор', is_system: true, permissions: [] }, { id: 2, name: 'Менеджер', is_system: true, permissions: [] }] }],
  ['GET', '/api/departments/', { body: [{ id: 4, name: 'Продажи' }] }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

const fillNew = async (login: string) => {
  await userEvent.click(await screen.findByRole('button', { name: 'Новый сотрудник' }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText(/^Email или телефон/), login)
  await within(dialog).findByRole('option', { name: 'Менеджер' })
  await userEvent.selectOptions(within(dialog).getByLabelText(/^Роль/), '2')
  return dialog
}

describe('Сотрудники', () => {
  it('список с ролью и отделом', async () => {
    loggedIn(base)
    renderApp('/settings/users')
    const row = (await screen.findByRole('button', { name: 'Мария' })).closest('tr')!
    expect(within(row).getByText('Менеджер')).toBeInTheDocument()
    expect(within(row).getByText('Продажи')).toBeInTheDocument()
  })

  it('создание нового пользователя отправляет пароль и имя', async () => {
    const m = loggedIn([['POST', '/api/users/', { status: 201, body: { id: 3, user_id: 3, email: 'n@x.kz', full_name: 'Новый', role: 2, is_active: true } }], ...base])
    renderApp('/settings/users')
    const dialog = await fillNew('n@x.kz')
    await userEvent.type(within(dialog).getByLabelText('Имя'), 'Новый')
    await userEvent.type(within(dialog).getByLabelText('Пароль'), 'S3cret-pass!')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ login: 'n@x.kz', full_name: 'Новый', role: 2, department: null, password: 'S3cret-pass!' }) })
    expect(await screen.findByText('Сотрудник создан')).toBeInTheDocument()
  })

  it('присоединение существующего: пароль не нужен и не отправляется, ответ без профиля даёт «добавлен»', async () => {
    const m = loggedIn([['POST', '/api/users/', { status: 201, body: { id: 3, user_id: 9, role: 2, role_name: 'Менеджер', department: null, is_active: true, login: 'old@x.kz' } }], ...base])
    renderApp('/settings/users')
    const dialog = await fillNew('old@x.kz')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ login: 'old@x.kz', full_name: '', role: 2, department: null }) })
    expect(await screen.findByText(/Существующий пользователь old@x.kz добавлен в компанию/)).toBeInTheDocument()
  })

  it('«для нового пользователя нужен пароль» ложится на поле', async () => {
    loggedIn([['POST', '/api/users/', { status: 400, body: { password: ['Для нового пользователя нужен пароль'] } }], ...base])
    renderApp('/settings/users')
    const dialog = await fillNew('n@x.kz')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Для нового пользователя нужен пароль')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Пароль')).toHaveAttribute('aria-invalid', 'true')
  })

  it('лимит тарифа (402 limit_exceeded) показывается понятным текстом', async () => {
    loggedIn([['POST', '/api/users/', { status: 402, body: { detail: 'Достигнут лимит тарифа', code: 'limit_exceeded' } }], ...base])
    renderApp('/settings/users')
    const dialog = await fillNew('n@x.kz')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText(/Достигнут лимит пользователей по тарифу/)).toBeInTheDocument()
  })

  it('правка: PATCH только с изменённым полем; запрет на свою роль показывается', async () => {
    let reply: { status: number; body: unknown } = { status: 200, body: users[1] }
    const m = loggedIn([['PATCH', '/api/users/2/', () => reply], ['PATCH', '/api/users/1/', { status: 403, body: { detail: 'Нельзя менять собственную роль', code: 'permission_denied' } }], ...base])
    renderApp('/settings/users')
    await userEvent.click(await screen.findByRole('button', { name: 'Мария' }))
    let dialog = await screen.findByRole('dialog')
    await within(dialog).findByRole('option', { name: 'Администратор' })
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Сотрудник активен' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH' && c.path === '/api/users/2/')?.body).toEqual({ is_active: false }) })
    reply = { status: 200, body: users[1] }
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    await userEvent.click(screen.getByRole('button', { name: 'Админ Админов' }))
    dialog = await screen.findByRole('dialog')
    await within(dialog).findByRole('option', { name: 'Менеджер' })
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Роль/), '2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Нельзя менять собственную роль')).toBeInTheDocument()
  })

  it('последний администратор: 400 показывается', async () => {
    loggedIn([['PATCH', '/api/users/2/', { status: 400, body: { detail: 'Нельзя отключить или понизить последнего администратора' } }], ...base])
    renderApp('/settings/users')
    await userEvent.click(await screen.findByRole('button', { name: 'Мария' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Сотрудник активен' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Нельзя отключить или понизить последнего администратора')).toBeInTheDocument()
  })

  it('без users.update имена не кнопки, без users.view - 403, в readonly «Новый сотрудник» отключена', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'users.update') } })
    renderApp('/settings/users')
    expect(await screen.findByText('Мария')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Мария' })).not.toBeInTheDocument()
  })

  it('в readonly создание отключено', async () => {
    loggedIn(base, { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/settings/users')
    expect(await screen.findByRole('button', { name: 'Новый сотрудник' })).toBeDisabled()
  })

  it('без users.view прямой заход (и отделы) даёт 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'users.view') } })
    renderApp('/settings/users')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
