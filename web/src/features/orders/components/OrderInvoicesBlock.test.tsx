import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../../test/fixtures'
import { makeInvoice } from '../../../test/finance'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { CURRENCIES, handbookBody, makeLine, makeOrder } from '../../../test/orders'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const base: MockRoutes = [
  ['GET', '/api/orders/5/', { body: makeOrder() }],
  ['GET', /^\/api\/order-lines\/\?order=5/, { body: page([makeLine()]) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
]

afterEach(() => {
  vi.unstubAllGlobals()
})

async function openFinanceTab() {
  const tab = await screen.findByRole('tab', { name: 'Финансы' })
  tab.click()
}

describe('Заказ: счета и оплаты', () => {
  it('показывает счета заказа, суммы и ссылку на новый счёт', async () => {
    const m = loggedIn([
      ...base,
      ['GET', /^\/api\/finance\/invoices\/\?/, { body: page([makeInvoice({ paid: '200.00', balance: '960.00', display_status: 'partial' })]) }],
    ])
    renderApp('/orders/5')
    await openFinanceTab()
    const block = await screen.findByRole('region', { name: 'Счета и оплаты' })
    const link = await within(block).findByRole('link', { name: 'СЧ-2026-00001' })
    expect(link).toHaveAttribute('href', '/finance/invoices/1')
    expect(within(block).getByText('Частично оплачен')).toBeInTheDocument()
    expect(within(block).getByText(/Выставлено/)).toBeInTheDocument()
    expect(within(block).getByRole('link', { name: 'Выставить счёт' })).toHaveAttribute('href', '/finance/invoices/new?order=5')
    const call = m.calls.find((c) => c.path.startsWith('/api/finance/invoices/?'))!
    expect(new URL(call.path, 'http://x').searchParams.get('order')).toBe('5')
  })

  it('без счетов — подсказка', async () => {
    loggedIn([...base, ['GET', /^\/api\/finance\/invoices\/\?/, { body: page([]) }]])
    renderApp('/orders/5')
    await openFinanceTab()
    expect(await screen.findByText('Счетов по заказу пока нет')).toBeInTheDocument()
  })

  it('без finance.view вкладки «Финансы» и запроса счетов нет', async () => {
    const m = loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.view') } })
    renderApp('/orders/5')
    await screen.findByRole('heading', { name: /ORD-2026-00005/ })
    expect(screen.queryByRole('tab', { name: 'Финансы' })).not.toBeInTheDocument()
    expect(m.calls.some((c) => c.path.startsWith('/api/finance/'))).toBe(false)
  })
})
