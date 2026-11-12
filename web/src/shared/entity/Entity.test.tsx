import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderWithProviders } from '../../test/renderApp'
import { EntityComments } from './EntityComments'
import { EntityHistory } from './EntityHistory'

const entry = (over: Record<string, unknown>) => ({
  id: 1, user: 7, action: 'update', object_type: 'forwarding.trip', object_id: '5', object_repr: 'TRP-1',
  changes: {}, changes_labels: {}, created_at: '2026-11-01T09:00:00Z', ...over,
})

describe('EntityHistory', () => {
  it('показывает кто и что изменил: было → стало с подписями полей', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/audit\//, { body: { count: 2, next: null, previous: null, results: [
        entry({ id: 2, changes: { carrier_price: ['100.00', '150.00'] }, changes_labels: { carrier_price: 'К оплате перевозчику' } }),
        entry({ id: 1, action: 'create', changes: { number: [null, 'TRP-1'], status_id: [null, 3] } }),
      ] } }],
      ['GET', '/api/users/', { body: [] }],
    ])
    renderWithProviders(<EntityHistory objectType="forwarding.trip" objectId={5} />)
    expect(await screen.findByText('К оплате перевозчику:')).toBeInTheDocument()
    expect(screen.getByText('100.00')).toBeInTheDocument()
    expect(screen.getByText('150.00')).toBeInTheDocument()
    expect(screen.getByText('Заполнено полей: 2')).toBeInTheDocument()
    expect(screen.getByText('Создано')).toBeInTheDocument()
    const call = m.calls.find((c) => c.path.startsWith('/api/audit/'))
    expect(call?.path).toContain('object_type=forwarding.trip')
    expect(call?.path).toContain('object_id=5')
  })

  it('без права company.view запрос не уходит, показано пояснение', async () => {
    const m = loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'company.view') } })
    renderWithProviders(<EntityHistory objectType="forwarding.trip" objectId={5} />)
    expect(await screen.findByText('История недоступна')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path.startsWith('/api/audit/'))).toBe(false)
  })

  it('пустой журнал - пустое состояние', async () => {
    loggedIn([
      ['GET', /^\/api\/audit\//, { body: { count: 0, next: null, previous: null, results: [] } }],
      ['GET', '/api/users/', { body: [] }],
    ])
    renderWithProviders(<EntityHistory objectType="core.client" objectId={1} />)
    expect(await screen.findByText('Изменений пока нет')).toBeInTheDocument()
  })
})

describe('EntityComments', () => {
  const comments = [{ id: 1, author: 'Анна', created_at: '2026-11-01T09:00:00Z', text: 'Позвонить водителю' }]

  it('показывает комментарии и отправляет новый кнопкой и по Ctrl+Enter', async () => {
    loggedIn()
    const onAdd = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(<EntityComments comments={comments} onAdd={onAdd} />)
    expect(await screen.findByText('Позвонить водителю')).toBeInTheDocument()
    const user = userEvent.setup()
    const field = screen.getByLabelText('Новый комментарий')
    const send = screen.getByRole('button', { name: 'Отправить' })
    expect(send).toBeDisabled()
    await user.type(field, '  Готово  ')
    await user.click(send)
    await waitFor(() => { expect(onAdd).toHaveBeenCalledWith('Готово') })
    await waitFor(() => { expect(field).toHaveValue('') })
    await user.type(field, 'Второй{Control>}{Enter}{/Control}')
    await waitFor(() => { expect(onAdd).toHaveBeenLastCalledWith('Второй') })
  })

  it('без onAdd - только чтение, поля ввода нет; без записей - пустое состояние', async () => {
    loggedIn()
    renderWithProviders(<EntityComments comments={[]} />)
    expect(await screen.findByText('Комментариев пока нет')).toBeInTheDocument()
    expect(screen.queryByLabelText('Новый комментарий')).not.toBeInTheDocument()
  })
})
