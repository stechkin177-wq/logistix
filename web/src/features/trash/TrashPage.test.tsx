import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const entries = [
  { code: 'orders', id: 5, label: 'ORD-2026-00005', deleted_at: '2026-10-30T05:00:00Z' },
  { code: 'trips', id: 9, label: 'C1', deleted_at: '2026-10-29T05:00:00Z' },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Корзина', () => {
  it('список с типами; фильтр по типу уходит как code', async () => {
    const m = loggedIn([['GET', /^\/api\/trash\/\?/, { body: page(entries) }]])
    renderApp('/trash?code=trips')
    const row = (await screen.findByText('ORD-2026-00005')).closest('tr')!
    expect(within(row).getByText('Заказ')).toBeInTheDocument()
    expect(new URL(m.calls.find((c) => c.path.startsWith('/api/trash/?'))!.path, 'http://x').searchParams.get('code')).toBe('trips')
  })

  it('«Восстановить» делает POST и обновляет список', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/trash\/\?/, { body: page(entries) }],
      ['POST', '/api/trash/orders/5/restore/', { body: { code: 'orders', id: 5, label: 'ORD-2026-00005' } }],
    ])
    renderApp('/trash')
    await userEvent.click(await screen.findByRole('button', { name: 'Восстановить ORD-2026-00005' }))
    await waitFor(() => { expect(m.count('POST', '/api/trash/orders/5/restore/')).toBe(1) })
    expect(await screen.findByText('Восстановлено: ORD-2026-00005')).toBeInTheDocument()
    await waitFor(() => { expect(m.count('GET', /^\/api\/trash\/\?/)).toBeGreaterThan(1) })
  })

  it('409 показывает сообщение сервера, 404 - «Не найдено»', async () => {
    let reply = { status: 409, body: { detail: 'Сначала восстановите клиента заказа' } }
    loggedIn([
      ['GET', /^\/api\/trash\/\?/, { body: page(entries) }],
      ['POST', '/api/trash/orders/5/restore/', () => reply],
    ])
    renderApp('/trash')
    await userEvent.click(await screen.findByRole('button', { name: 'Восстановить ORD-2026-00005' }))
    expect(await screen.findByText('Сначала восстановите клиента заказа')).toBeInTheDocument()
    reply = { status: 404, body: { detail: 'Not found.' } }
    await userEvent.click(screen.getByRole('button', { name: 'Восстановить ORD-2026-00005' }))
    expect(await screen.findByText('Не найдено')).toBeInTheDocument()
  })

  it('без trash.update кнопка отключена, без trash.view - 403', async () => {
    loggedIn([['GET', /^\/api\/trash\/\?/, { body: page(entries) }]], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trash.update') } })
    renderApp('/trash')
    expect(await screen.findByRole('button', { name: 'Восстановить ORD-2026-00005' })).toBeDisabled()
  })

  it('прямой заход без trash.view даёт 403', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'trash.view') } })
    renderApp('/trash')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })

  it('в режиме только чтения «Восстановить» отключена', async () => {
    loggedIn([['GET', /^\/api\/trash\/\?/, { body: page(entries) }]], { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/trash')
    expect(await screen.findByRole('button', { name: 'Восстановить ORD-2026-00005' })).toBeDisabled()
  })
})
