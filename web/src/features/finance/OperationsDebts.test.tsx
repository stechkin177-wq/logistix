import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import type { DebtRow, OperationsResponse } from './types'

const OPS: OperationsResponse = {
  count: 1, next: null, previous: null,
  results: [{ id: 1, date: '2026-10-05', order: { id: 5, number: 'ORD-2026-00005' }, client: { id: 7, name: 'ТОО Ромашка' }, title: 'Перевозка', category: 'Услуги', income: '1000.00', expense: '300.00', currency: 'USD', is_base: false }],
  summary: { income_kzt: '450000.00', expense_kzt: '135000.00', diff_kzt: '315000.00', by_currency: { USD: { income: '1000.00', expense: '300.00', diff: '700.00' } }, unconverted: 2 },
}
const opsRoute = (body: OperationsResponse = OPS): MockRoutes[number] => ['GET', /^\/api\/finance\/operations\/\?/, { body }]

const DEBT: DebtRow = {
  id: 7, name: 'ТОО Ромашка', issued_kzt: '1000.00', paid_kzt: '300.00', balance_kzt: '700.00', overdue_kzt: '400.00',
  by_currency: { KZT: { issued: '1000.00', paid: '300.00', balance: '700.00' } }, credit_limit: '2000.00', limit_usage_pct: '35.00',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Операции', () => {
  it('выводит строки, итоги в тенге, разбивку по валютам и число строк без курса', async () => {
    loggedIn([opsRoute()])
    renderApp('/finance?tab=operations')
    const row = (await screen.findByText('Перевозка')).closest('tr')!
    expect(within(row).getByText('ORD-2026-00005')).toBeInTheDocument()
    const summary = screen.getByRole('group', { name: 'Итоги' })
    expect(within(summary).getByText(/315\s000,00/)).toBeInTheDocument()
    expect(within(summary).getByText(/USD/)).toBeInTheDocument()
    expect(screen.getByText(/Строк без курса: 2/)).toBeInTheDocument()
  })

  it('новая модель: подписи итогов берутся из ответа (USD), исключённые записи помечены', async () => {
    const body: OperationsResponse = {
      ...OPS,
      results: [{ ...OPS.results[0]!, base_status: 'prior_base' as const }],
      summary: {
        ...OPS.summary, currency: 'USD', unconverted: 0,
        excluded: { is_partial: true, count: 2, orders: 1, prior_base: { count: 2, by_currency: { KZT: { income: '1000.00', expense: '300.00' } } }, no_rate: { count: 0, by_currency: {} } },
      },
    }
    loggedIn([opsRoute(body)])
    renderApp('/finance?tab=operations')
    await screen.findByText('Перевозка')
    expect(screen.getByText('Доход, USD')).toBeInTheDocument()
    expect(screen.getByText('Расход, USD')).toBeInTheDocument()
    expect(screen.getByText('Разница, USD')).toBeInTheDocument()
    expect(screen.queryByText('Доход, KZT')).not.toBeInTheDocument()
    expect(screen.getByText(/В итог не вошло записей: 2/)).toBeInTheDocument()
    expect(screen.getByText(/вне итога: прежняя база/)).toBeInTheDocument()
  })

  it('фильтры уходят на сервер; выгрузка скачивает файл с теми же фильтрами', async () => {
    const m = loggedIn([
      opsRoute(),
      ['GET', /^\/api\/finance\/operations\/export\//, { body: 'x', headers: { 'Content-Disposition': 'attachment; filename="operations.xlsx"' } }],
    ])
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const user = userEvent.setup()
    renderApp('/finance?tab=operations&date_from=2026-10-01&category=Услуги')
    await screen.findByText('Перевозка')
    const list = m.calls.find((c) => c.path.startsWith('/api/finance/operations/?'))!
    const q = new URL(list.path, 'http://x').searchParams
    expect(q.get('date_from')).toBe('2026-10-01')
    expect(q.get('category')).toBe('Услуги')
    await user.click(screen.getByRole('button', { name: 'Выгрузить в Excel' }))
    await waitFor(() => {
      const exp = m.calls.find((c) => c.path.startsWith('/api/finance/operations/export/'))
      expect(exp).toBeDefined()
      expect(new URL(exp!.path, 'http://x').searchParams.get('category')).toBe('Услуги')
    })
  })

  it('пустой журнал показывает подсказку', async () => {
    loggedIn([opsRoute({ ...OPS, count: 0, results: [] })])
    renderApp('/finance?tab=operations')
    expect(await screen.findByText('Операций нет')).toBeInTheDocument()
  })
})

describe('Долги', () => {
  const clients: MockRoutes[number] = ['GET', '/api/finance/debts/clients/', { body: { results: [DEBT, { ...DEBT, id: 8, name: 'ИП Лютик', credit_limit: '0.00', limit_usage_pct: null }] } }]
  const carriers: MockRoutes[number] = ['GET', '/api/finance/debts/carriers/', { body: { results: [{ ...DEBT, id: 6, name: 'ИП Быстров', credit_limit: undefined, limit_usage_pct: undefined }] } }]

  it('клиенты: остаток, просрочка, использование лимита и «без лимита»', async () => {
    loggedIn([clients, carriers])
    renderApp('/finance?tab=debts')
    const row = (await screen.findByRole('link', { name: 'ТОО Ромашка' })).closest('tr')!
    expect(within(row).getAllByText(/700,00/).length).toBeGreaterThan(0)
    expect(within(row).getByText(/35/)).toBeInTheDocument()
    const lutik = screen.getByRole('link', { name: 'ИП Лютик' }).closest('tr')!
    expect(within(lutik).getByText('без лимита')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ТОО Ромашка' })).toHaveAttribute('href', '/finance?tab=invoices&client=7')
  })

  it('переключение на перевозчиков грузит их долги, колонок лимита нет', async () => {
    loggedIn([clients, carriers])
    const user = userEvent.setup()
    renderApp('/finance?tab=debts')
    await screen.findByRole('link', { name: 'ТОО Ромашка' })
    await user.selectOptions(screen.getByLabelText('Контрагенты'), 'carriers')
    expect(await screen.findByRole('link', { name: 'ИП Быстров' })).toHaveAttribute('href', '/finance?tab=invoices&carrier=6')
    expect(screen.queryByRole('columnheader', { name: 'Кредитный лимит' })).not.toBeInTheDocument()
  })

  it('пустое состояние', async () => {
    loggedIn([['GET', '/api/finance/debts/clients/', { body: { results: [] } }]])
    renderApp('/finance?tab=debts')
    expect(await screen.findByText('Долгов нет')).toBeInTheDocument()
  })
})
