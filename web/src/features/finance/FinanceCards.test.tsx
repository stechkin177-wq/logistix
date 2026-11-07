import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn } from '../../test/harness'
import { renderWithProviders } from '../../test/renderApp'
import { OrderFinanceBlock } from './OrderFinanceBlock'
import { TripFinanceBlock } from './TripFinanceBlock'
import type { ExpenseRow, OrderFinance, TripFinance } from './ledgerTypes'

const KZT = { id: 1, code: 'KZT', name: 'Тенге' }
const EXP: ExpenseRow = {
  id: 9, kind: 'carrier_transport', title: 'Перевозка TR-1', category: { id: 3, code: 'OTHER', name: 'Прочее' }, amount: '100.00', currency: KZT,
  expense_date: '2026-07-10', status: 'active', source: 'carrier_price_sync', trip: { id: 4, number: 'TR-1' }, carrier: null,
  needs_review: true, review_reason: 'invoice_variance', allocations: [], allocated: '100.00', unallocated: '0.00', linked_total: '90.00',
  invoice_variance: '-10.00', void_reason: '', order_amount: '60.00',
}
const ORDER: OrderFinance = {
  engine: 'new', order: { id: 7, number: 'ORD-7', currency: KZT }, incomes: [], expenses: [EXP], invoices: [],
  totals: { revenue: '500.00', cost: '60.00', profit: '440.00', margin_pct: '88.00' }, needs_review: true,
}
const TRIP = (can: boolean): TripFinance => ({
  engine: 'new', trip: { id: 4, number: 'TR-1', carrier: { id: 2, name: 'ИП Быстров' }, carrier_price: '100.00', currency: KZT },
  expense: can ? null : EXP, expenses: can ? [] : [EXP], invoices: [], can_create_expense: can, needs_review: !can, invoice_variance: can ? null : '-10.00',
})

afterEach(() => { vi.unstubAllGlobals() })

describe('Финансы заказа', () => {
  it('итоги, расходы с долей заказа и предупреждение о проверке', async () => {
    loggedIn([['GET', '/api/orders/7/finance/', { body: ORDER }]])
    renderWithProviders(<OrderFinanceBlock orderId={7} />)
    expect(await screen.findByText('По заказу есть расходы, требующие проверки')).toBeInTheDocument()
    const totals = screen.getByRole('group', { name: 'Итоги' })
    expect(within(totals).getByText(/440,00/)).toBeInTheDocument()
    const item = screen.getByText('Перевозка TR-1').closest('li')!
    expect(within(item).getByText(/60,00/)).toBeInTheDocument() // доля заказа, а не весь расход (100,00)
    expect(within(item).queryByText(/100,00/)).not.toBeInTheDocument()
    expect(screen.getByText(/Нужна проверка/)).toBeInTheDocument()
  })

  it('ошибка загрузки показывается баннером', async () => {
    loggedIn([['GET', '/api/orders/7/finance/', { status: 500, body: {} }]])
    renderWithProviders(<OrderFinanceBlock orderId={7} />)
    expect(await screen.findByText(/сервер|Сервер|ошибка/i)).toBeInTheDocument()
  })
})

describe('Финансы рейса', () => {
  it('кнопка создаёт расход из цены рейса один раз даже при двойном нажатии', async () => {
    let finish: () => void = () => {}
    const m = loggedIn([
      ['GET', '/api/trips/4/finance/', { body: TRIP(true) }],
      ['POST', '/api/finance/trips/4/carrier-expense/', () => new Promise((res) => { finish = () => { res({ status: 201, body: { engine: 'new' } }) } })],
    ])
    const user = userEvent.setup()
    renderWithProviders(<TripFinanceBlock tripId={4} />)
    const button = await screen.findByRole('button', { name: 'Создать расход из цены рейса' })
    await user.click(button)
    await user.click(button)
    expect(button).toBeDisabled()
    finish()
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1) })
  })

  it('при созданном расходе кнопки нет, виден бейдж и расхождение со счётом', async () => {
    loggedIn([['GET', '/api/trips/4/finance/', { body: TRIP(false) }]])
    renderWithProviders(<TripFinanceBlock tripId={4} />)
    expect(await screen.findByText(/Нужна проверка/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Создать расход из цены рейса' })).not.toBeInTheDocument()
    expect(screen.getAllByText(/Расхождение/).length).toBeGreaterThan(0)
  })

  it('ошибка expense_exists показывается пользователю', async () => {
    loggedIn([
      ['GET', '/api/trips/4/finance/', { body: TRIP(true) }],
      ['POST', '/api/finance/trips/4/carrier-expense/', { status: 409, body: { detail: 'Расход по этому рейсу уже создан', code: 'expense_exists' } }],
    ])
    const user = userEvent.setup()
    renderWithProviders(<TripFinanceBlock tripId={4} />)
    await user.click(await screen.findByRole('button', { name: 'Создать расход из цены рейса' }))
    expect(await screen.findByText('Расход по этому рейсу уже создан')).toBeInTheDocument()
  })
})
