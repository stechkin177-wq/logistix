import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { makeInvoice } from '../../test/finance'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'
import type { Payment } from './types'

const PAYMENT: Payment = {
  id: 3, invoice: { id: 1, number: 'СЧ-2026-00001', direction: 'out' }, date: '2026-10-31', amount: '200.00', rate_to_kzt: '1.000000',
  method: 'bank', payment_ref: 'П-7', comment: '', fx_difference_kzt: '0.00', created_at: '2026-10-31T05:00:00Z',
}

const invoiceRoute = (inv = makeInvoice()): MockRoutes[number] => ['GET', '/api/finance/invoices/1/', { body: inv }]
const paymentsRoute = (items: Payment[] = []): MockRoutes[number] => ['GET', /^\/api\/finance\/invoices\/1\/payments\//, { body: page(items) }]
const LIMIT_ERROR = { status: 400, body: { detail: 'Превышен кредитный лимит клиента', code: 'credit_limit_exceeded' } }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Счёт: карточка', () => {
  it('показывает итоги, позиции и оплаты', async () => {
    loggedIn([invoiceRoute(makeInvoice({ paid: '200.00', balance: '960.00', display_status: 'partial' })), paymentsRoute([PAYMENT])])
    renderApp('/finance/invoices/1')
    expect(await screen.findByRole('heading', { name: /СЧ-2026-00001/ })).toBeInTheDocument()
    expect(screen.getByText('Частично оплачен')).toBeInTheDocument()
    expect(screen.getByText('Перевозка')).toBeInTheDocument()
    expect(await screen.findByText('П-7')).toBeInTheDocument()
    expect(screen.getAllByText(/960,00/).length).toBeGreaterThan(0)
  })

  it('оплата: сумма по умолчанию = остатку, больше остатка нельзя, успешная отправка', async () => {
    const m = loggedIn([
      invoiceRoute(makeInvoice({ balance: '1160.00' })),
      paymentsRoute(),
      ['POST', '/api/finance/invoices/1/payments/', { status: 201, body: PAYMENT }],
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/1')
    await user.click(await screen.findByRole('button', { name: 'Добавить оплату' }))
    const dialog = await screen.findByRole('dialog')
    const amount = within(dialog).getByLabelText(/^Сумма/)
    expect(amount).toHaveValue('1160.00')
    await user.clear(amount)
    await user.type(amount, '2000')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText(/Сумма больше остатка/)).toBeInTheDocument()
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
    await user.clear(amount)
    await user.type(amount, '500.50')
    const date = within(dialog).getByLabelText(/^Дата оплаты/)
    await user.clear(date)
    await user.type(date, '2026-10-31')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toMatchObject({ amount: '500.50', date: '2026-10-31', method: 'bank' })
    })
  })

  it('черновик: выставление; превышение лимита открывает диалог причины и повторяет запрос', async () => {
    let attempt = 0
    const m = loggedIn([
      invoiceRoute(makeInvoice({ status: 'draft', display_status: 'draft', number: '' })),
      paymentsRoute(),
      ['POST', '/api/finance/invoices/1/issue/', (): { status: number; body: unknown } => (attempt++ === 0 ? LIMIT_ERROR : { status: 200, body: makeInvoice() })],
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/1')
    await user.click(await screen.findByRole('button', { name: 'Выставить' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Превышен кредитный лимит клиента', { selector: 'h2, h1, [id]' })).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Выставить сверх лимита' }))
    expect(await within(dialog).findByText('Укажите причину')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/^Причина/), 'согласовано')
    await user.click(within(dialog).getByRole('button', { name: 'Выставить сверх лимита' }))
    await waitFor(() => {
      const posts = m.calls.filter((c) => c.path === '/api/finance/invoices/1/issue/')
      expect(posts).toHaveLength(2)
      expect(posts[1]?.body).toEqual({ override_reason: 'согласовано' })
    })
  })

  it('без права обхода лимита диалог только объясняет, кнопки подтверждения нет', async () => {
    loggedIn(
      [
        invoiceRoute(makeInvoice({ status: 'draft', display_status: 'draft', number: '' })),
        paymentsRoute(),
        ['POST', '/api/finance/invoices/1/issue/', LIMIT_ERROR],
      ],
      { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.override_limit') } },
    )
    const user = userEvent.setup()
    renderApp('/finance/invoices/1')
    await user.click(await screen.findByRole('button', { name: 'Выставить' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/только сотрудник с правом/)).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Выставить сверх лимита' })).not.toBeInTheDocument()
  })

  it('отмена доступна только с finance.cancel_invoice и подтверждается', async () => {
    const m = loggedIn([invoiceRoute(), paymentsRoute(), ['POST', '/api/finance/invoices/1/cancel/', { body: makeInvoice({ status: 'cancelled', display_status: 'cancelled' }) }]])
    const user = userEvent.setup()
    renderApp('/finance/invoices/1')
    await user.click(await screen.findByRole('button', { name: 'Отменить счёт' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Отменить счёт' }))
    await waitFor(() => {
      expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/finance/invoices/1/cancel/')).toBe(true)
    })
  })

  it('без finance.cancel_invoice кнопки отмены нет', async () => {
    loggedIn([invoiceRoute(), paymentsRoute()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.cancel_invoice') } })
    renderApp('/finance/invoices/1')
    await screen.findByRole('heading', { name: /СЧ-2026-00001/ })
    expect(screen.queryByRole('button', { name: 'Отменить счёт' })).not.toBeInTheDocument()
  })

  it('оплаченный счёт не предлагает добавить оплату', async () => {
    loggedIn([invoiceRoute(makeInvoice({ balance: '0.00', paid: '1160.00', display_status: 'paid' })), paymentsRoute([PAYMENT])])
    renderApp('/finance/invoices/1')
    await screen.findByRole('heading', { name: /СЧ-2026-00001/ })
    expect(screen.queryByRole('button', { name: 'Добавить оплату' })).not.toBeInTheDocument()
  })
})
