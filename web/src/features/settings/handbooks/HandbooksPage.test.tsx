import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { handbookBody, hv } from '../../../test/orders'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const list = [
  { code: 'order_status', name: 'Статусы заказов', group: 'Статусы', values_count: 2 },
  { code: 'currency', name: 'Валюты', group: 'Финансы', values_count: 1 },
]
const statuses = [hv('order_status', 1, 'Новый', { is_initial: true }), hv('order_status', 2, 'В работе')]
const base: MockRoutes = [
  ['GET', '/api/handbooks/', { body: list }],
  ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', statuses) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', [hv('currency', 11, 'Тенге', { code: 'KZT' })]) }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Справочники', () => {
  it('слева группы со счётчиками, справа значения выбранного', async () => {
    loggedIn(base)
    renderApp('/settings/handbooks')
    const nav = await screen.findByRole('navigation', { name: 'Справочники' })
    expect(within(nav).getByText('Статусы')).toBeInTheDocument()
    expect(within(nav).getByRole('button', { name: /Валюты/ })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Новый' })).toBeInTheDocument()
    await userEvent.click(within(nav).getByRole('button', { name: /Валюты/ }))
    expect(await screen.findByRole('button', { name: 'Тенге' })).toBeInTheDocument()
  })

  it('«Сделать начальным» шлёт make-initial только для неначального значения', async () => {
    const m = loggedIn([['POST', '/api/handbook-values/2/make-initial/', { body: statuses[1] }], ...base])
    renderApp('/settings/handbooks')
    expect(screen.queryByRole('button', { name: 'Сделать начальным: Новый' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Сделать начальным: В работе' }))
    await waitFor(() => { expect(m.count('POST', '/api/handbook-values/2/make-initial/')).toBe(1) })
    await waitFor(() => { expect(m.count('GET', '/api/handbooks/?code=order_status')).toBeGreaterThan(1) })
  })

  it('удаление используемого значения: 409 с рекомендацией деактивировать', async () => {
    loggedIn([['DELETE', '/api/handbook-values/2/', { status: 409, body: { detail: 'Значение используется в записях и не может быть удалено; деактивируйте его' } }], ...base])
    renderApp('/settings/handbooks')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить значение В работе' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    expect(await screen.findByText(/деактивируйте его/)).toBeInTheDocument()
  })

  it('деактивация шлёт PATCH is_active; добавление значения шлёт код справочника', async () => {
    const m = loggedIn([
      ['PATCH', '/api/handbook-values/2/', { body: statuses[1] }],
      ['POST', '/api/handbook-values/', { status: 201, body: statuses[1] }],
      ...base,
    ])
    renderApp('/settings/handbooks')
    await userEvent.click(await screen.findByRole('button', { name: 'Отключить В работе' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ is_active: false }) })
    await userEvent.click(screen.getByRole('button', { name: 'Добавить значение' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Название/), 'Отменён')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Конечное значение' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ handbook: 'order_status', name: 'Отменён', code: '', is_initial: false, is_final: true, is_active: true }) })
  })

  it('системное значение: код и «конечное» заблокированы, удаление и отключение недоступны, переименование работает', async () => {
    const system = [
      hv('order_status', 1, 'Новый', { is_initial: true }),
      hv('order_status', 6, 'Завершён', { code: 'completed', is_final: true, is_system: true }),
    ]
    const m = loggedIn([
      ['PATCH', '/api/handbook-values/6/', { body: system[1] }],
      ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', system) }],
      ...base,
    ])
    renderApp('/settings/handbooks')
    expect(await screen.findByText('системное')).toBeInTheDocument()
    // кнопки удаления и отключения системного значения: удаления нет, отключение недоступно с подсказкой
    expect(screen.queryByRole('button', { name: 'Удалить значение Завершён' })).not.toBeInTheDocument()
    const off = screen.getByRole('button', { name: 'Отключить Завершён' })
    expect(off).toBeDisabled()
    expect(off).toHaveAttribute('title', expect.stringContaining('Системное значение'))
    // у обычного значения всё по-прежнему доступно
    expect(screen.getByRole('button', { name: 'Удалить значение Новый' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Завершён' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Код')).toBeDisabled()
    expect(within(dialog).getByRole('checkbox', { name: 'Конечное значение' })).toBeDisabled()
    expect(within(dialog).getByRole('checkbox', { name: 'Активно' })).toBeDisabled()
    const name = within(dialog).getByLabelText(/^Название/)
    await userEvent.clear(name)
    await userEvent.type(name, 'Выполнен')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ name: 'Выполнен', order: 6, is_initial: false }) })
  })

  it('«Начальное значение» только у справочников статусов', async () => {
    loggedIn(base)
    renderApp('/settings/handbooks?code=currency')
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить значение' }))
    expect(within(await screen.findByRole('dialog')).queryByRole('checkbox', { name: 'Начальное значение' })).not.toBeInTheDocument()
  })

  it('в режиме только чтения и без прав кнопки записи отключены; без handbooks.view - 403', async () => {
    loggedIn(base, { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/settings/handbooks')
    expect(await screen.findByRole('button', { name: 'Добавить значение' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Отключить В работе' })).toBeDisabled()
  })

  it('без handbooks.view прямой заход даёт 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'handbooks.view') } })
    renderApp('/settings/handbooks')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
