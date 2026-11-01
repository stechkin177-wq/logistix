import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { page } from '../../test/fixtures'
import { mockFetch } from '../../test/fetchMock'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const CLIENT = {
  id: 7, name: 'ТОО Ромашка', bin_iin: '123456789012', type: 1, type_name: 'Юридическое лицо', status: 'active',
  credit_limit: '1234567.89', orders_count: 3, notes: '', contacts: [{ id: 5, name: 'Иван', position: '', phone: '+77001112233', email: '' }],
  created_at: '2026-10-01T05:00:00Z',
}
const TYPES = { code: 'client_type', name: 'Типы', group: 'g', values: [
  { id: 1, handbook: 'client_type', name: 'Юридическое лицо', code: '', order: 1, is_initial: false, is_final: false, is_active: true },
  { id: 2, handbook: 'client_type', name: 'ИП', code: '', order: 2, is_initial: false, is_final: false, is_active: true },
  { id: 3, handbook: 'client_type', name: 'Старый тип', code: '', order: 3, is_initial: false, is_final: false, is_active: false },
] }

const typesRoute: Parameters<typeof mockFetch>[0][number] = ['GET', '/api/handbooks/?code=client_type', { body: TYPES }]

describe('Клиенты', () => {
  it('показывает строки, группирует деньги и считает заказы', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute])
    renderApp('/clients')
    expect(await screen.findByText('ТОО Ромашка')).toBeInTheDocument()
    expect(screen.getByText(/^1\s234\s567,89$/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '3' })).toHaveAttribute('href', '/orders?client=7')
  })

  it('поиск отправляет q на сервер и пишет его в адрес', async () => {
    const m = loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute])
    const { router } = renderApp('/clients')
    await screen.findByText('ТОО Ромашка')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Поиск' }), 'ром')
    await waitFor(() => { expect(m.calls.some((c) => c.path.includes('q=%D1%80%D0%BE%D0%BC')) ).toBe(true) })
    expect(router.state.location.search).toContain('q=')
  })

  it('пустой список показывает пустое состояние с кнопкой создания', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([]) }], typesRoute])
    renderApp('/clients')
    expect(await screen.findByText('Клиентов пока нет')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Новый клиент' }).length).toBeGreaterThan(1)
  })

  it('ошибка загрузки показывает сообщение и повтор', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { status: 500, body: { detail: 'x' } }], typesRoute])
    renderApp('/clients')
    expect(await screen.findByText('Ошибка сервера. Попробуйте позже')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })

  it('ошибка БИН/ИИН с сервера ложится на поле, а не в баннер', async () => {
    loggedIn([
      ['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }],
      typesRoute,
      ['POST', '/api/clients/', { status: 400, body: { bin_iin: ['Контрагент с таким БИН/ИИН уже есть'] } }],
    ])
    renderApp('/clients')
    await screen.findByText('ТОО Ромашка')
    await userEvent.click(screen.getAllByRole('button', { name: 'Новый клиент' })[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Новый')
    await userEvent.type(within(drawer).getByLabelText('БИН/ИИН'), '123456789012')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    const field = await within(drawer).findByLabelText('БИН/ИИН')
    await waitFor(() => { expect(field).toHaveAttribute('aria-invalid', 'true') })
    expect(within(drawer).getByText('Контрагент с таким БИН/ИИН уже есть')).toBeInTheDocument()
    expect(field).toHaveFocus()
  })

  it('клиентская проверка: без названия запрос не уходит', async () => {
    const m = loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([]) }], typesRoute])
    renderApp('/clients')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый клиент' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByText('Обязательное поле')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('контакты: добавить, изменить и убрать строку; id существующих уходят на сервер', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }],
      typesRoute,
      ['PATCH', '/api/clients/7/', { body: CLIENT }],
    ])
    renderApp('/clients')
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Ромашка' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Добавить контакт' }))
    const names = within(drawer).getAllByLabelText(/^Имя/)
    expect(names).toHaveLength(2)
    await userEvent.type(names[1]!, 'Пётр')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Убрать контакт 1' }))
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'PATCH')!.body as { contacts: { id?: number; name: string }[] }
    expect(body.contacts).toEqual([expect.objectContaining({ name: 'Пётр' })])
    expect(body.contacts[0]).not.toHaveProperty('id')
  })

  it('409 «контакт используется» показывается в баннере формы', async () => {
    loggedIn([
      ['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }],
      typesRoute,
      ['PATCH', '/api/clients/7/', { status: 409, body: { detail: 'Контакт используется в заказах и не может быть удалён', code: 'contact_in_use' } }],
    ])
    renderApp('/clients')
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Ромашка' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Убрать контакт 1' }))
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByRole('alert')).toHaveTextContent('Контакт используется в заказах')
  })

  it('в списке типов только активные значения (кроме текущего)', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute])
    renderApp('/clients')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый клиент' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    const select = await within(drawer).findByLabelText('Тип')
    await waitFor(() => { expect(within(select).getByRole('option', { name: 'ИП' })).toBeInTheDocument() })
    expect(within(select).queryByRole('option', { name: 'Старый тип' })).not.toBeInTheDocument()
  })

  it('удаление скрыто без clients.delete и подтверждается диалогом с правом', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute], {
      session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'clients.delete') },
    })
    renderApp('/clients')
    await screen.findByText('ТОО Ромашка')
    expect(screen.queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument()
  })

  it('удаление: подтверждение и DELETE', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }],
      typesRoute,
      ['DELETE', '/api/clients/7/', { status: 204 }],
    ])
    renderApp('/clients')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить: ТОО Ромашка' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(m.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE')).toBe(true) })
    await waitFor(() => { expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument() })
  })

  it('режим только чтения отключает запись', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute], {
      session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } },
    })
    renderApp('/clients')
    await screen.findByText('ТОО Ромашка')
    expect(screen.getAllByRole('button', { name: 'Новый клиент' })[0]).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить: ТОО Ромашка' })).toBeDisabled()
  })

  it('без права clients.view открывается страница 403', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'clients.view') } })
    renderApp('/clients')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })

  it('контакты отключены, если нельзя сохранять (нет clients.update)', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute], {
      session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'clients.update') },
    })
    renderApp('/clients')
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Ромашка' }))
    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByLabelText(/^Имя/)).toBeDisabled()
    expect(within(drawer).getByRole('button', { name: 'Добавить контакт' })).toBeDisabled()
    expect(within(drawer).getByRole('button', { name: 'Убрать контакт 1' })).toBeDisabled()
  })

  it('режим только чтения отключает контакты', async () => {
    loggedIn([['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }], typesRoute], {
      session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } },
    })
    renderApp('/clients')
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Ромашка' }))
    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByRole('button', { name: 'Добавить контакт' })).toBeDisabled()
  })

  it('страница за последней (404) возвращает на первую', async () => {
    loggedIn([
      ['GET', /^\/api\/clients\/\?.*page=7/, { status: 404, body: { detail: 'Неверная страница.' } }],
      ['GET', /^\/api\/clients\/\?/, { body: page([CLIENT]) }],
      typesRoute,
    ])
    const { router } = renderApp('/clients?page=7')
    expect(await screen.findByText('ТОО Ромашка')).toBeInTheDocument()
    expect(router.state.location.search).not.toContain('page=7')
  })
})
