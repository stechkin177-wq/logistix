import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import type { EngineInfo, ExpenseRow, IncomeRow } from './ledgerTypes'

const KZT = { id: 1, code: 'KZT', name: 'Тенге' }
const engine = (e: EngineInfo['engine'], frozen = false): MockRoutes[number] => [
  'GET', '/api/finance/engine/', { body: { engine: e, financial_writes_frozen: frozen, base_currency: KZT } },
]
const empty = { count: 0, next: null, previous: null, results: [] }

const INCOME: IncomeRow = {
  id: 5, order: { id: 7, number: 'ORD-7' }, kind: 'service', title: 'Экспедирование', category: '', amount: '250.00',
  currency: KZT, status: 'planned', recognized_on: null, recognition_basis: '', delivered_on: null, base_amount: null, fx_rate: null,
  trip: null, void_reason: '', legacy: false,
}
const EXPENSE: ExpenseRow = {
  id: 9, kind: 'carrier_transport', title: 'Перевозка TR-1', category: { id: 3, code: 'OTHER', name: 'Прочее' }, amount: '100.00', currency: KZT,
  expense_date: '2026-07-10', status: 'active', source: 'carrier_price_sync', trip: { id: 4, number: 'TR-1' }, carrier: { id: 2, name: 'ИП Быстров' },
  needs_review: true, review_reason: 'invoice_variance', allocations: [{ id: 1, order: { id: 7, number: 'ORD-7' }, trip: null, amount: '60.00' }],
  allocated: '60.00', unallocated: '40.00', linked_total: '90.00', invoice_variance: '-10.00', void_reason: '',
}
const page = <T,>(rows: T[]) => ({ count: rows.length, next: null, previous: null, results: rows })

afterEach(() => { vi.unstubAllGlobals() })

describe('Разделы «Доходы» и «Расходы» по режиму учёта', () => {
  it('в legacy вкладок нет, при new - есть', async () => {
    loggedIn([engine('legacy'), ['GET', /^\/api\/finance\/invoices\//, { body: empty }]])
    const { unmount } = renderApp('/finance')
    await screen.findByRole('tab', { name: 'Счета' })
    expect(screen.queryByRole('tab', { name: 'Доходы' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Расходы' })).not.toBeInTheDocument()
    unmount()
    loggedIn([engine('new'), ['GET', /^\/api\/finance\/invoices\//, { body: empty }]])
    renderApp('/finance')
    expect(await screen.findByRole('tab', { name: 'Доходы' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Расходы' })).toBeInTheDocument()
  })

  it('прямая ссылка на вкладку доходов при legacy возвращает к счетам', async () => {
    loggedIn([engine('legacy'), ['GET', /^\/api\/finance\/invoices\//, { body: empty }]])
    renderApp('/finance?tab=incomes')
    expect(await screen.findByRole('tab', { name: 'Счета', selected: true })).toBeInTheDocument()
  })
})

describe('Доходы', () => {
  it('список, аннулирование с причиной и защита от повторной отправки', async () => {
    let resolveVoid: () => void = () => {}
    const m = loggedIn([
      engine('new'),
      ['GET', /^\/api\/finance\/incomes\//, { body: page([INCOME]) }],
      ['POST', '/api/finance/incomes/5/void/', () => new Promise((res) => { resolveVoid = () => { res({ body: { ...INCOME, status: 'void' } }) } })],
    ])
    const user = userEvent.setup()
    renderApp('/finance?tab=incomes')
    const row = (await screen.findByText('Экспедирование')).closest('tr')!
    expect(within(row).getByText('Запланирован')).toBeInTheDocument()
    await user.click(within(row).getByRole('button', { name: 'Аннулировать' }))
    const dialog = await screen.findByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Аннулировать' })
    expect(submit).toBeDisabled() // причина обязательна
    await user.type(within(dialog).getByLabelText(/Причина/), 'Дубль')
    await user.click(submit)
    await user.click(submit)
    expect(submit).toBeDisabled()
    resolveVoid()
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    const posts = m.calls.filter((c) => c.method === 'POST' && c.path.endsWith('/void/'))
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({ reason: 'Дубль' })
  })

  it('ошибка сервера finance_frozen показывается в диалоге понятным текстом', async () => {
    loggedIn([
      engine('new'),
      ['GET', /^\/api\/finance\/incomes\//, { body: page([INCOME]) }],
      ['POST', '/api/finance/incomes/5/void/', { status: 423, body: { detail: 'Финансовые изменения временно остановлены администратором', code: 'finance_frozen' } }],
    ])
    const user = userEvent.setup()
    renderApp('/finance?tab=incomes')
    await user.click(await screen.findByRole('button', { name: 'Аннулировать' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Причина/), 'Дубль')
    await user.click(within(dialog).getByRole('button', { name: 'Аннулировать' }))
    expect(await within(dialog).findByText(/временно остановлены/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Аннулировать' })).toBeEnabled() // можно повторить
  })

  it('без права finance.create кнопка «Новая услуга» отключена', async () => {
    loggedIn(
      [engine('new'), ['GET', /^\/api\/finance\/incomes\//, { body: page([INCOME]) }]],
      { session: { permissions: ALL_PERMISSIONS.filter((p) => !['finance.create', 'finance.update', 'finance.delete'].includes(p)) } },
    )
    renderApp('/finance?tab=incomes')
    expect(await screen.findByRole('button', { name: 'Новая услуга' })).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'Отметить оказание' })).toBeDisabled()
  })
})

describe('Расходы', () => {
  it('бейдж «нужна проверка» с расхождением и панель долей по раскрытию', async () => {
    loggedIn([engine('new'), ['GET', /^\/api\/finance\/expenses\//, { body: page([EXPENSE]) }]])
    const user = userEvent.setup()
    renderApp('/finance?tab=expenses')
    const row = (await screen.findByText('Перевозка TR-1')).closest('tr')!
    expect(within(row).getByText(/Нужна проверка/)).toHaveTextContent('-10.00')
    expect(within(row).queryByRole('list', { name: 'Доли расхода' })).not.toBeInTheDocument()
    await user.click(within(row).getByRole('button', { name: /Доли \(1\)/ }))
    const list = within(row).getByRole('list', { name: 'Доли расхода' })
    expect(within(list).getByText('ORD-7')).toBeInTheDocument()
    expect(within(list).getByText(/Не распределено/)).toBeInTheDocument()
  })

  it('фильтр «только требующие проверки» уходит на сервер', async () => {
    const m = loggedIn([engine('new'), ['GET', /^\/api\/finance\/expenses\//, { body: page([EXPENSE]) }]])
    renderApp('/finance?tab=expenses&needs_review=true&date_from=2026-07-01')
    await screen.findByText('Перевозка TR-1')
    const call = m.calls.find((c) => c.path.startsWith('/api/finance/expenses/?'))!
    const q = new URL(call.path, 'http://x').searchParams
    expect(q.get('needs_review')).toBe('true')
    expect(q.get('date_from')).toBe('2026-07-01')
  })
})
