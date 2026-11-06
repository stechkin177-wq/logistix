import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Отделы', () => {
  it('создание, дубликат на поле, удаление с подтверждением и ошибкой сервера', async () => {
    let post: { status: number; body: unknown } = { status: 400, body: { name: ['Отдел с таким названием уже есть'] } }
    const m = loggedIn([
      ['GET', '/api/departments/', { body: [{ id: 4, name: 'Продажи' }] }],
      ['POST', '/api/departments/', () => post],
      ['DELETE', '/api/departments/4/', { status: 409, body: { detail: 'В отделе есть сотрудники' } }],
    ])
    renderApp('/settings/departments')
    await userEvent.click(await screen.findByRole('button', { name: 'Новый отдел' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Название/), 'Продажи')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Отдел с таким названием уже есть')).toBeInTheDocument()
    post = { status: 201, body: { id: 5, name: 'Склад' } }
    await userEvent.clear(within(dialog).getByLabelText(/^Название/))
    await userEvent.type(within(dialog).getByLabelText(/^Название/), 'Склад')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'POST').at(-1)?.body).toEqual({ name: 'Склад' }) })
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить отдел Продажи' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    expect(await screen.findByText('В отделе есть сотрудники')).toBeInTheDocument()
  })

  it('без users.delete кнопки удаления нет; без users.view - 403', async () => {
    loggedIn([['GET', '/api/departments/', { body: [{ id: 4, name: 'Продажи' }] }]], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'users.delete') } })
    renderApp('/settings/departments')
    await screen.findByText('Продажи')
    expect(screen.queryByRole('button', { name: /Удалить отдел/ })).not.toBeInTheDocument()
  })

  it('без users.view даёт 403', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'users.view') } })
    renderApp('/settings/departments')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
