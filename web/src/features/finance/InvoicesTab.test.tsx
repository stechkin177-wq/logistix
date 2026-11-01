import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { makeInvoice } from '../../test/finance'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const listRoute = (items = [makeInvoice()]): MockRoutes[number] => ['GET', /^\/api\/finance\/invoices\/\?/, { body: page(items) }]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Счета: список', () => {
  it('выводит номер-ссылку, контрагента, суммы и статус', async () => {
    loggedIn([listRoute()])
    renderApp('/finance')
    const link = await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    expect(link).toHaveAttribute('href', '/finance/invoices/1')
    const row = link.closest('tr')!
    expect(within(row).getByText('ТОО Ромашка')).toBeInTheDocument()
    expect(within(row).getByText('Выставлен')).toBeInTheDocument()
    expect(within(row).getAllByText(/1\s160,00/)).toHaveLength(2) // «Всего» и «Остаток»
  })

  it('черновик без номера показывается как «Черновик №id»', async () => {
    loggedIn([listRoute([makeInvoice({ id: 9, number: '', status: 'draft', display_status: 'draft' })])])
    renderApp('/finance')
    expect(await screen.findByRole('link', { name: 'Черновик №9' })).toBeInTheDocument()
  })

  it('фильтры уходят на сервер, неверный статус в адресе игнорируется', async () => {
    const m = loggedIn([listRoute()])
    renderApp('/finance?tab=invoices&status=overdue&direction=in&search=ПС&order=5&status=junk')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    const call = m.calls.find((c) => c.path.startsWith('/api/finance/invoices/?'))!
    const q = new URL(call.path, 'http://x').searchParams
    expect(q.get('status')).toBe('overdue')
    expect(q.get('direction')).toBe('in')
    expect(q.get('search')).toBe('ПС')
    expect(q.get('order')).toBe('5')
  })

  it('смена статуса в фильтре обновляет запрос', async () => {
    const m = loggedIn([listRoute()])
    const user = userEvent.setup()
    renderApp('/finance')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    await user.selectOptions(screen.getByLabelText('Статус'), 'overdue')
    await waitFor(() => {
      expect(m.calls.some((c) => c.path.includes('status=overdue'))).toBe(true)
    })
  })

  it('пустой список показывает подсказку', async () => {
    loggedIn([listRoute([])])
    renderApp('/finance')
    expect(await screen.findByText('Счетов пока нет')).toBeInTheDocument()
  })

  it('кнопки создания отключены без finance.create', async () => {
    loggedIn([listRoute()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.create') } })
    renderApp('/finance')
    await screen.findByRole('link', { name: 'СЧ-2026-00001' })
    expect(screen.getByRole('button', { name: 'Выставить счёт' })).toBeDisabled()
  })
})
