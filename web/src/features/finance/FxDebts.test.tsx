import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import type { DebtRow, DebtsExcluded, Payment, RealizedSummary } from './types'

const NO_EXCLUDED: DebtsExcluded = {
  is_partial: false, count: 0,
  no_rate: { count: 0, by_currency: {} }, prior_base: { count: 0, by_currency: {} }, no_base_rate: { count: 0, by_currency: {} },
}
const ROW: DebtRow = {
  id: 7, name: 'ТОО Ромашка', issued_kzt: '45000.00', paid_kzt: '0.00', balance_kzt: '45000.00', overdue_kzt: '45000.00',
  by_currency: { USD: { issued: '100.00', paid: '0.00', balance: '100.00' } },
  credit_limit: '0.00', limit_usage_pct: null,
  balance: { USD: '100.00' }, overdue: { USD: '100.00' },
  applied_rate: { USD: { rate: '480.000000', rate_date: '2026-06-10', source: 'via_kzt' } },
  balance_base: '48000.00', overdue_base: '48000.00', carrying_base: '45000.00', unrealized_diff: '3000.00',
  excluded: NO_EXCLUDED, is_partial: false,
}

const debtsRoute = (over: Record<string, unknown> = {}): MockRoutes[number] => [
  'GET', '/api/finance/debts/clients/',
  { body: { results: [ROW], base_currency: 'KZT', as_of: '2026-06-20', is_partial: false, excluded: NO_EXCLUDED, ...over } },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Долги в базовой валюте (новая модель)', () => {
  it('показывает исходную сумму, эквивалент в базе с применённым курсом и раздельные колонки разниц', async () => {
    loggedIn([debtsRoute()])
    renderApp('/finance?tab=debts')
    const row = (await screen.findByRole('link', { name: 'ТОО Ромашка' })).closest('tr')!
    expect(within(row).getAllByText(/USD 100,00/).length).toBe(2) // остаток и просрочка
    const base = within(row).getAllByText(/48\s000,00\sKZT/)[0]!
    expect(base.closest('span[title]')).toHaveAttribute('title', expect.stringContaining('480'))
    expect(base.closest('span[title]')).toHaveAttribute('title', expect.stringContaining('2026-06-10'))
    expect(base.closest('span[title]')).toHaveAttribute('title', expect.stringContaining('через тенге'))
    expect(within(row).getByText(/3\s000,00\sKZT/)).toBeInTheDocument()
    for (const name of ['Остаток, исходная валюта', 'Эквивалент в базе, KZT', 'Просрочено, исходная валюта', 'Просрочено, KZT', 'Балансовая стоимость, KZT', 'Курсовая разница нереализованная, KZT']) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument()
    }
    // реализованной разницы на странице долгов нет, общей суммы - тоже
    expect(screen.queryByRole('columnheader', { name: 'Курсовая разница реализованная, KZT' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Выставлено, KZT' })).not.toBeInTheDocument()
  })

  it('неполные данные: пометка с причинами и суммами в исходной валюте', async () => {
    const excluded: DebtsExcluded = {
      is_partial: true, count: 3,
      no_rate: { count: 1, by_currency: { EUR: { open: '5.00', overdue: '0.00', equivalent_base: '0.00' } } },
      prior_base: { count: 1, by_currency: { USD: { open: '100.00', overdue: '0.00', equivalent_base: '9600.00' } } },
      no_base_rate: { count: 1, by_currency: { USD: { open: '20.00', overdue: '0.00', equivalent_base: '1920.00' } } },
    }
    loggedIn([debtsRoute({ is_partial: true, excluded })])
    renderApp('/finance?tab=debts')
    const hint = await screen.findByText(/Неполные данные: счетов с исключениями 3/)
    const title = hint.getAttribute('title') ?? ''
    expect(title).toContain('Нет курса на дату отчёта: 1')
    expect(title).toMatch(/Курс счёта в прежней базовой валюте \(вне итога базы\): 1: 100,00\sUSD/)
    expect(title).toContain('Без базового курса счёта')
  })

  it('прежний режим (без base_currency): прежние колонки в KZT и нет пометок', async () => {
    const legacyRow = { id: 7, name: 'ТОО Ромашка', issued_kzt: '1000.00', paid_kzt: '300.00', balance_kzt: '700.00', overdue_kzt: '400.00', by_currency: { KZT: { issued: '1000.00', paid: '300.00', balance: '700.00' } } }
    loggedIn([['GET', '/api/finance/debts/clients/', { body: { results: [legacyRow] } }]])
    renderApp('/finance?tab=debts')
    await screen.findByRole('link', { name: 'ТОО Ромашка' })
    expect(screen.getByRole('columnheader', { name: 'Выставлено, KZT' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: /Эквивалент в базе/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/Неполные данные/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Выгрузить в Excel' })).not.toBeInTheDocument()
  })

  it('выгрузка Excel долгов доступна только в новой модели', async () => {
    const m = loggedIn([
      debtsRoute(),
      ['GET', /^\/api\/finance\/debts\/clients\/export\//, { body: 'x', headers: { 'Content-Disposition': 'attachment; filename="debts-out.xlsx"' } }],
    ])
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const user = userEvent.setup()
    renderApp('/finance?tab=debts')
    await screen.findByRole('link', { name: 'ТОО Ромашка' })
    await user.click(screen.getByRole('button', { name: 'Выгрузить в Excel' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path.startsWith('/api/finance/debts/clients/export/'))).toBe(true) })
  })
})

const PAY: Payment = {
  id: 3, invoice: { id: 1, number: 'СЧ-2026-00001', direction: 'out' }, date: '2026-05-20', amount: '40.00', rate_to_kzt: '460.000000',
  method: 'bank', payment_ref: '', comment: '', fx_difference_kzt: '400.00', created_at: '2026-05-20T05:00:00Z',
  base_currency: 'KZT', rate_to_base: '460.000000', invoice_rate_to_base: '450.000000', fx_realized_base: '400.00', fx_status: 'ok',
}
const SUMMARY: RealizedSummary = {
  base_currency: 'KZT', fx_realized_base: '400.00', by_direction: { out: '400.00', in: '0.00' }, is_partial: false,
  excluded: { count: 0, prior_base: { count: 0, by_currency: {} }, no_base_rate: { count: 0, by_currency: {} } },
}

describe('Оплаты: реализованная курсовая разница', () => {
  it('новая модель: колонка и итог в базовой валюте', async () => {
    loggedIn([['GET', /^\/api\/finance\/payments\/\?/, { body: { ...page([PAY]), summary: SUMMARY } }]])
    renderApp('/finance?tab=payments')
    const link = await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    const row = link.closest('tr')!
    expect(within(row).getByText(/400,00\sKZT/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Курсовая разница реализованная, KZT' })).toBeInTheDocument()
    const total = screen.getByRole('group', { name: 'Реализованная курсовая разница' })
    expect(within(total).getByText(/400,00\sKZT/)).toBeInTheDocument()
  })

  it('оплата без базового курса: прочерк с пояснением и пометка неполноты', async () => {
    const noRate: Payment = { ...PAY, fx_realized_base: null, fx_status: 'no_base_rate' }
    const partial: RealizedSummary = {
      ...SUMMARY, fx_realized_base: '0.00', is_partial: true,
      excluded: { count: 1, prior_base: { count: 0, by_currency: {} }, no_base_rate: { count: 1, by_currency: { USD: '40.00' } } },
    }
    loggedIn([['GET', /^\/api\/finance\/payments\/\?/, { body: { ...page([noRate]), summary: partial } }]])
    renderApp('/finance?tab=payments')
    const row = (await screen.findByRole('link', { name: 'СЧ-2026-00001' })).closest('tr')!
    expect(within(row).getByTitle('Нет базового курса счёта или оплаты')).toBeInTheDocument()
    expect(screen.getByText(/Оплат вне итога реализованной разницы: 1/)).toBeInTheDocument()
  })

  it('прежний режим: прежняя колонка в KZT', async () => {
    const legacy: Payment = {
      id: PAY.id, invoice: PAY.invoice, date: PAY.date, amount: PAY.amount, rate_to_kzt: PAY.rate_to_kzt, method: PAY.method,
      payment_ref: PAY.payment_ref, comment: PAY.comment, fx_difference_kzt: PAY.fx_difference_kzt, created_at: PAY.created_at,
    }
    loggedIn([['GET', /^\/api\/finance\/payments\/\?/, { body: page([legacy]) }]])
    renderApp('/finance?tab=payments')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    expect(screen.getByRole('columnheader', { name: 'Курсовая разница, KZT' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Реализованная курсовая разница' })).not.toBeInTheDocument()
  })
})
