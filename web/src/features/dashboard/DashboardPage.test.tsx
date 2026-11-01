import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const STATUSES = [
  { status_id: 1, status: 'Новый', count: 0 },
  { status_id: 2, status: 'В работе', count: 0 },
  { status_id: 3, status: 'Завершён', count: 0 },
]
const SUMMARY = {
  month: '2026-10', active_orders: 4, completed_orders: 9, clients: 12, carriers: 5, unassigned_orders: 2,
  orders_by_status: [{ status_id: 1, status: 'Новый', count: 3 }, { status_id: 2, status: 'В работе', count: 1 }, { status_id: 3, status: 'Завершён', count: 0 }],
  month_profit: '1234567.80', month_margin_pct: '12.50',
}

describe('Дашборд', () => {
  it('показывает карточки, все статусы и финансы', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: SUMMARY }]])
    renderApp('/')
    expect(await screen.findByText('Активные заказы')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/^1\s234\s567,80$/)).toBeInTheDocument()
    expect(screen.getByText('12,50 %')).toBeInTheDocument()
    const bars = screen.getByRole('region', { name: 'Заказы по статусам' })
    expect(within(bars).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByRole('link', { name: /Без перевозчика/ })).toHaveAttribute('href', '/orders?unassigned=1')
  })

  it('нулевые данные: нули, все статусы с нулями и пустое состояние', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, active_orders: 0, completed_orders: 0, clients: 0, carriers: 0, unassigned_orders: 0, orders_by_status: STATUSES, month_profit: '0.00', month_margin_pct: null } }]])
    renderApp('/')
    expect(await screen.findByText('Данных пока нет')).toBeInTheDocument()
    const bars = screen.getByRole('region', { name: 'Заказы по статусам' })
    expect(within(bars).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('Маржа за месяц').nextSibling).toHaveTextContent('—')
    expect(screen.queryByText('NaN')).not.toBeInTheDocument()
  })

  it('без finance.view финансовых карточек нет', async () => {
    loggedIn([['GET', '/api/dashboard/summary/', { body: { ...SUMMARY, month_profit: null, month_margin_pct: null } }]])
    renderApp('/')
    await screen.findByText('Активные заказы')
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
