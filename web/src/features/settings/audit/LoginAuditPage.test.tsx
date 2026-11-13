import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const row = (over: Record<string, unknown>) => ({
  id: 1, user: 7, action: 'login', object_type: 'core.user', object_id: '7', object_repr: 'x', ip: '10.0.0.5',
  changes: { user_agent: 'Mozilla/5.0 Test' }, changes_labels: {}, created_at: '2026-11-01T09:00:00Z', ...over,
})
const USERS: MockRoutes[number] = ['GET', '/api/users/', { body: [{ id: 1, role: 1, role_name: 'А', department: null, user_id: 7, full_name: 'Анна Админова', email: 'a@x.kz', phone: null, is_active: true }] }]

describe('Аудит входов', () => {
  it('показывает входы и неудачные попытки с IP, устройством и причиной; запрос по login,login_failed', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/audit\//, { body: { count: 2, next: null, previous: null, results: [
        row({ id: 2, action: 'login_failed', changes: { reason: 'bad_credentials', user_agent: 'Mozilla/5.0 Test' } }),
        row({ id: 1 }),
      ] } }],
      USERS,
    ])
    renderApp('/settings/audit')
    expect(await screen.findByRole('heading', { name: 'Аудит входов' })).toBeInTheDocument()
    const table = await screen.findByRole('table')
    expect(await within(table).findByText('Неудачная попытка')).toBeInTheDocument()
    expect(within(table).getByText('Неверный пароль')).toBeInTheDocument()
    expect(within(table).getAllByText('Анна Админова').length).toBeGreaterThan(0)
    expect(within(table).getAllByText('10.0.0.5')).toHaveLength(2)
    const q = new URL(m.calls.find((c) => c.path.startsWith('/api/audit/'))!.path, 'http://x').searchParams
    expect(q.get('actions')).toBe('login,login_failed')
  })

  it('фильтр события сужает запрос', async () => {
    const m = loggedIn([['GET', /^\/api\/audit\//, { body: { count: 0, next: null, previous: null, results: [] } }], USERS])
    renderApp('/settings/audit')
    await userEvent.selectOptions(await screen.findByLabelText('Событие'), 'login_failed')
    await screen.findByText('Событий входа за период нет')
    const last = m.calls.filter((c) => c.path.startsWith('/api/audit/')).at(-1)!
    expect(new URL(last.path, 'http://x').searchParams.get('actions')).toBe('login_failed')
  })

  it('без audit.view пункта нет и страница закрыта', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'audit.view') } })
    renderApp('/settings/audit')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(screen.queryByRole('heading', { name: 'Аудит входов' })).not.toBeInTheDocument()
  })
})
