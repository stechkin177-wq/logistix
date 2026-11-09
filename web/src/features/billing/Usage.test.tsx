import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const ROW = { unit: 'ед.', scope: 'total', enforced: true }
const USAGE = {
  results: [
    { ...ROW, code: 'max_vehicles', name: 'Техника', limit: 5, usage: 4, exceeded: false, state: 'near' },
    { ...ROW, code: 'max_drivers', name: 'Водители', limit: 2, usage: 3, exceeded: true, state: 'exceeded' },
    { ...ROW, code: 'max_clients', name: 'Клиенты', limit: null, usage: 9, exceeded: false, state: 'ok' },
  ],
  warnings: [
    { ...ROW, code: 'max_drivers', name: 'Водители', limit: 2, usage: 3, exceeded: true, state: 'exceeded' },
    { ...ROW, code: 'max_vehicles', name: 'Техника', limit: 5, usage: 4, exceeded: false, state: 'near' },
  ],
}

describe('Лимиты тарифа', () => {
  it('баннер владельцу: превышение выше приближения, с фактическим использованием', async () => {
    loggedIn([['GET', '/api/billing/usage/', { body: USAGE }]])
    renderApp('/')
    const banner = await screen.findByText(/Использование выше лимита тарифа: Водители — 3 из 2/)
    expect(banner).toHaveTextContent('Данные сохранены')
    expect(within(banner.closest('[role="status"]') as HTMLElement).getByRole('link', { name: 'Подробнее' })).toHaveAttribute('href', '/settings/company')
  })

  it('без предупреждений баннера нет', async () => {
    loggedIn([['GET', '/api/billing/usage/', { body: { results: [], warnings: [] } }]])
    renderApp('/')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(screen.queryByText(/лимит/i)).not.toBeInTheDocument()
  })

  it('без права управления модулями запрос использования не отправляется', async () => {
    const m = loggedIn([['GET', '/api/billing/usage/', { body: USAGE }]], {
      session: { permissions: ['orders.view', 'clients.view'] },
    })
    renderApp('/')
    await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(m.calls.some((c) => c.path === '/api/billing/usage/')).toBe(false)
    expect(screen.queryByText(/Использование выше лимита/)).not.toBeInTheDocument()
  })

  it('страница компании: список лимитов и использование, безлимитные не показываются', async () => {
    loggedIn([
      ['GET', '/api/billing/usage/', { body: USAGE }],
      ['GET', '/api/billing/subscription/', { body: { plan: { code: 'x', name: 'Тариф' }, status: 'active', is_free_period: false, ends_at: null, days_left: null } }],
    ])
    renderApp('/settings/company')
    const block = await screen.findByRole('region', { name: 'Лимиты тарифа и использование' })
    expect(await within(block).findByText('Техника')).toBeInTheDocument()
    expect(within(block).getByText('приближается к лимиту')).toBeInTheDocument()
    expect(within(block).getByText('превышен')).toBeInTheDocument()
    expect(within(block).queryByText('Клиенты')).not.toBeInTheDocument()
    expect(within(block).getByText(/Данные сохранены/)).toBeInTheDocument()
  })
})
