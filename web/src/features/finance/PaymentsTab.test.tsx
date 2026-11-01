import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'
import type { Payment } from './types'

const P: Payment = {
  id: 3, invoice: { id: 1, number: 'СЧ-2026-00001', direction: 'out' }, date: '2026-10-31', amount: '200.00', rate_to_kzt: '1.000000',
  method: 'cash', payment_ref: 'П-7', comment: '', fx_difference_kzt: '0.00', created_at: '2026-10-31T05:00:00Z',
}
const route = (items = [P]): MockRoutes[number] => ['GET', /^\/api\/finance\/payments\/\?/, { body: page(items) }]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Оплаты: журнал', () => {
  it('выводит оплату со ссылкой на счёт и способом', async () => {
    loggedIn([route()])
    renderApp('/finance?tab=payments')
    const link = await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    expect(link).toHaveAttribute('href', '/finance/invoices/1')
    const row = link.closest('tr')!
    expect(within(row).getByText('Наличные')).toBeInTheDocument()
    expect(within(row).getByText('П-7')).toBeInTheDocument()
  })

  it('фильтр направления уходит на сервер', async () => {
    const m = loggedIn([route()])
    const user = userEvent.setup()
    renderApp('/finance?tab=payments')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    await user.selectOptions(screen.getByLabelText('Направление'), 'in')
    await waitFor(() => { expect(m.calls.some((c) => c.path.includes('direction=in'))).toBe(true) })
  })

  it('удаление оплаты подтверждается, без finance.delete кнопки нет', async () => {
    const m = loggedIn([route(), ['DELETE', '/api/finance/payments/3/', { status: 204 }]])
    const user = userEvent.setup()
    renderApp('/finance?tab=payments')
    await user.click(await screen.findByRole('button', { name: 'Удалить оплату от 2026-10-31' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'DELETE')).toBe(true) })
  })

  it('без finance.delete кнопки удаления нет', async () => {
    loggedIn([route()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.delete') } })
    renderApp('/finance?tab=payments')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    expect(screen.queryByRole('button', { name: /Удалить оплату/ })).not.toBeInTheDocument()
  })

  it('пустой журнал показывает подсказку', async () => {
    loggedIn([route([])])
    renderApp('/finance?tab=payments')
    expect(await screen.findByText('Оплат пока нет')).toBeInTheDocument()
  })
})
