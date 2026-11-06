import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const STATUSES = [
  { status_id: 1, status: 'Новый', count: 0 },
  { status_id: 2, status: 'В работе', count: 0 },
  { status_id: 3, status: 'Завершён', count: 0 },
]
const SUMMARY = {
  month: '2026-10', active_orders: 4, completed_orders: 9, clients: 12, carriers: 5, unassigned_orders: 2,
  orders_by_status: [{ status_id: 1, status: 'Новый', count: 3 }, { status_id: 2, status: 'В работе', count: 1 }, { status_id: 3, status: 'Завершён', count: 0 }],
  month_profit: '1234567.80', month_margin_pct: '12.50', currency: 'KZT', excluded_orders: 0,
}

describe('Дашборд', () => {
  it('заказы в другой валюте: пометка с числом рядом с прибылью', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, excluded_orders: 3 } }]])
    renderApp('/')
    expect(await screen.findByText(/^1\s234\s567,80\sKZT$/)).toBeInTheDocument()
    expect(screen.getByText('В прибыль не вошли заказы в другой валюте (не KZT): 3')).toBeInTheDocument()
  })

  it('без finance.view пометки о валюте нет', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, month_profit: null, month_margin_pct: null, currency: null, excluded_orders: null } }]])
    renderApp('/')
    expect(await screen.findByText('Активные заказы')).toBeInTheDocument()
    expect(screen.queryByText(/в другой валюте/)).not.toBeInTheDocument()
  })

  it('показывает карточки, все статусы и финансы', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: SUMMARY }]])
    renderApp('/')
    expect(await screen.findByText('Активные заказы')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/^1\s234\s567,80\sKZT$/)).toBeInTheDocument()
    expect(screen.queryByText(/в другой валюте/)).not.toBeInTheDocument()
    expect(screen.getByText('12,50 %')).toBeInTheDocument()
    const bars = screen.getByRole('region', { name: 'Заказы по статусам' })
    expect(within(bars).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByRole('link', { name: /Без перевозчика/ })).toHaveAttribute('href', '/orders?unassigned=1')
  })

  it('нулевые данные: нули, все статусы с нулями и пустое состояние', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, active_orders: 0, completed_orders: 0, clients: 0, carriers: 0, unassigned_orders: 0, orders_by_status: STATUSES, month_profit: '0.00', month_margin_pct: null, currency: 'KZT', excluded_orders: 0 } }]])
    renderApp('/')
    expect(await screen.findByText('Данных пока нет')).toBeInTheDocument()
    const bars = screen.getByRole('region', { name: 'Заказы по статусам' })
    expect(within(bars).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('Маржа за месяц').nextSibling).toHaveTextContent('—')
    expect(screen.queryByText('NaN')).not.toBeInTheDocument()
  })

  it('без finance.view финансовых карточек нет', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, month_profit: null, month_margin_pct: null, currency: null, excluded_orders: null } }]])
    renderApp('/')
    await screen.findByText(SUMMARY.clients.toString())
    expect(screen.queryByText('Прибыль за месяц')).not.toBeInTheDocument()
    expect(screen.queryByText('Маржа за месяц')).not.toBeInTheDocument()
  })

  it('ошибка загрузки: сообщение и повтор', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { status: 403, body: { detail: 'x', code: 'module_disabled' } }]])
    renderApp('/')
    expect(await screen.findByText('Модуль не подключён')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Дашборд: финансовые плитки', () => {
  const summaryRoute = ['GET', '/api/dashboard/summary/', { body: SUMMARY }] as MockRoutes[number]
  const finance = { currency: 'KZT', client_debt_kzt: '500000.00', overdue_kzt: '120000.00', payable_kzt: '80000.00', month_profit_kzt: '0.00', month_margin_pct: null, fx_difference_kzt: '0.00', unconverted: 0 }

  it('с finance.view показывает долг клиентов, просрочку и к оплате перевозчикам', async () => {
    loggedIn([summaryRoute, ['GET', '/api/finance/summary/', { body: finance }]])
    renderApp('/')
    const debt = await screen.findByText('Долг клиентов')
    expect(debt.closest('a')).toHaveAttribute('href', '/finance?tab=debts')
    expect(screen.getByText(/500\s000,00/)).toBeInTheDocument()
    expect(screen.getByText('Просрочено').closest('a')).toHaveAttribute('href', '/finance?tab=invoices&status=overdue&direction=out')
    expect(screen.getByText('К оплате перевозчикам')).toBeInTheDocument()
  })

  it('без finance.view плиток нет и запрос не отправляется', async () => {
    const m = loggedIn([summaryRoute], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.view') } })
    renderApp('/')
    await screen.findByText(SUMMARY.clients.toString())
    expect(screen.queryByText('Долг клиентов')).not.toBeInTheDocument()
    expect(m.calls.some((c) => c.path.startsWith('/api/finance/summary'))).toBe(false)
  })
})
