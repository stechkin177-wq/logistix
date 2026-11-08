import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeIssued } from '../../test/documents'
import { makeInvoice } from '../../test/finance'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, ORDER_STATUSES, handbookBody, makeOrder } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp, renderWithProviders } from '../../test/renderApp'
import { IssueDocumentButton } from './IssueDocumentButton'
import { TRIP_STATUSES, makeTrip } from '../../test/trips'

const caps = (pdf: boolean): MockRoutes[number] => ['GET', '/api/documents/capabilities/', { body: { pdf_available: pdf } }]
const orderRoutes: MockRoutes = [
  ['GET', '/api/orders/5/', { body: makeOrder() }],
  ['GET', '/api/handbooks/?code=order_status', { body: handbookBody('order_status', ORDER_STATUSES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
  ['GET', '/api/users/', { body: [] }],
  ['GET', '/api/clients/7/', { body: { id: 7, name: 'ТОО Ромашка', contacts: [] } }],
]
const without = (code: string) => ({ permissions: ALL_PERMISSIONS.filter((p) => p !== code) })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Выдача документов: заказ', () => {
  it('нажатие выдаёт документ с источником и открывает диалог с номером', async () => {
    const m = loggedIn([
      ...orderRoutes, caps(true),
      ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ id: 4, kind: 'order_request', number: 'ЗК-7' }) }],
    ])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Заявка клиента' }))
    expect(await screen.findByText('Документ ЗК-7 выдан')).toBeInTheDocument()
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'order_request', order: 5 })
  })

  it('DOCX и PDF скачиваются через авторизованный запрос, PDF скрыта без pdf_available', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const m = loggedIn([
      ...orderRoutes, caps(true),
      ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ id: 4, number: 'ЗК-7' }) }],
      ['GET', /^\/api\/documents\/issued\/4\/download\//, { body: 'x', headers: { 'Content-Disposition': 'attachment; filename="a.docx"' } }],
    ])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Заявка клиента' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: /Скачать PDF/ }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/documents/issued/4/download/?format=pdf')).toBe(true) })
    await userEvent.click(within(dialog).getByRole('button', { name: /Скачать DOCX/ }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/documents/issued/4/download/?format=docx')).toBe(true) })
    expect(m.calls.find((c) => c.path.includes('download'))?.headers.Authorization).toBe('Bearer a')
  })

  it('без pdf_available в диалоге только DOCX', async () => {
    loggedIn([...orderRoutes, caps(false), ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ number: 'ЗК-7' }) }]])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Заявка клиента' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByRole('button', { name: /Скачать DOCX/ })
    expect(within(dialog).queryByRole('button', { name: /Скачать PDF/ })).not.toBeInTheDocument()
  })

  it('без documents.create кнопка отключена', async () => {
    loggedIn(orderRoutes, { session: without('documents.create') })
    renderApp('/orders/5')
    expect(await screen.findByRole('button', { name: 'Заявка клиента' })).toBeDisabled()
  })

  it('без модуля logistics кнопка скрыта, с модулем показана', async () => {
    loggedIn([], { session: { modules: [] } })
    const first = renderWithProviders(<IssueDocumentButton kind="order_request" source={{ order: 5 }} label="Заявка клиента" />)
    await waitFor(() => { expect(screen.queryByRole('button')).not.toBeInTheDocument() })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByRole('button', { name: 'Заявка клиента' })).not.toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()
    loggedIn([])
    renderWithProviders(<IssueDocumentButton kind="order_request" source={{ order: 5 }} label="Заявка клиента" />)
    expect(await screen.findByRole('button', { name: 'Заявка клиента' })).toBeInTheDocument()
  })

  it('требует модуль documents и модуль-владелец вида: акт - finance, заявка - logistics', async () => {
    const hidden = async (modules: string[], kind: 'act' | 'order_request') => {
      loggedIn([], { session: { modules } })
      const view = renderWithProviders(<IssueDocumentButton kind={kind} source={{ order: 5 }} label="Док" />)
      await new Promise((resolve) => setTimeout(resolve, 50))
      const absent = screen.queryByRole('button', { name: 'Док' }) === null
      view.unmount()
      vi.unstubAllGlobals()
      return absent
    }
    expect(await hidden(['logistics', 'finance'], 'order_request')).toBe(true) // нет documents
    expect(await hidden(['documents', 'finance'], 'order_request')).toBe(true) // нет logistics
    expect(await hidden(['documents', 'logistics'], 'act')).toBe(true) // нет finance
    loggedIn([], { session: { modules: ['documents', 'finance'] } })
    renderWithProviders(<IssueDocumentButton kind="act" source={{ invoice: 5 }} label="Док" />)
    expect(await screen.findByRole('button', { name: 'Док' })).toBeInTheDocument()
  })

  it('source_not_ready показывает причину сервера в диалоге', async () => {
    loggedIn([...orderRoutes, caps(true), ['POST', '/api/documents/issued/', { status: 400, body: { detail: 'У рейса не указан перевозчик.', code: 'source_not_ready' } }]])
    renderApp('/orders/5')
    await userEvent.click(await screen.findByRole('button', { name: 'Заявка клиента' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('У рейса не указан перевозчик.')).toBeInTheDocument()
  })

  it('повторное нажатие не создаёт второй документ, пока идёт запрос', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => { release = resolve })
    const m = loggedIn([
      ...orderRoutes, caps(true),
      ['POST', '/api/documents/issued/', async () => { await gate; return { status: 201, body: makeIssued({ number: 'ЗК-7' }) } }],
    ])
    renderApp('/orders/5')
    const button = await screen.findByRole('button', { name: 'Заявка клиента' })
    await userEvent.dblClick(button)
    await userEvent.click(button)
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    release()
    expect(await screen.findByText('Документ ЗК-7 выдан')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })
})

describe('Выдача документов: счёт', () => {
  const invoiceRoutes = (inv = makeInvoice()): MockRoutes => [
    ['GET', '/api/finance/invoices/1/', { body: inv }],
    ['GET', /^\/api\/finance\/invoices\/1\/payments\//, { body: page([]) }],
  ]

  it('у выставленного счёта клиенту есть «Счёт на оплату» и «Акт»; акт отправляет invoice', async () => {
    const m = loggedIn([...invoiceRoutes(), caps(true), ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ number: 'АКТ-1' }) }]])
    renderApp('/finance/invoices/1')
    expect(await screen.findByRole('button', { name: 'Счёт на оплату' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Акт' }))
    await screen.findByText('Документ АКТ-1 выдан')
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'act', invoice: 1 })
  })

  it.each(['draft', 'cancelled'] as const)('у счёта в статусе %s кнопок документов нет', async (status) => {
    loggedIn(invoiceRoutes(makeInvoice({ status, display_status: status })))
    renderApp('/finance/invoices/1')
    await screen.findByRole('heading', { name: /СЧ-2026-00001/ })
    expect(screen.queryByRole('button', { name: 'Акт' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Счёт на оплату' })).not.toBeInTheDocument()
  })

  it('у счёта перевозчика кнопок документов нет', async () => {
    loggedIn(invoiceRoutes(makeInvoice({ direction: 'in', client: null, carrier: { id: 6, name: 'ИП Быстров' } })))
    renderApp('/finance/invoices/1')
    await screen.findByRole('heading', { name: /СЧ-2026-00001/ })
    expect(screen.queryByRole('button', { name: 'Акт' })).not.toBeInTheDocument()
  })
})

describe('Выдача документов: рейс и клиент', () => {
  const tripRoutes = (trip = makeTrip()): MockRoutes => [
    ['GET', /^\/api\/trips\/\?/, { body: page([trip]) }],
    ['GET', '/api/trips/90/', { body: trip }],
    ['GET', '/api/handbooks/?code=trip_status', { body: handbookBody('trip_status', TRIP_STATUSES) }],
    ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
  ]

  it('в рейсе с перевозчиком есть договор-заявка и CMR; запрос несёт trip', async () => {
    const m = loggedIn([...tripRoutes(), caps(true), ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ number: 'ДЗ-1' }) }]])
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: 'ORD-2026-00005-1' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'CMR' })).toBeInTheDocument()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Договор-заявка перевозчику' }))
    await screen.findByText('Документ ДЗ-1 выдан')
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'carrier_order', trip: 90 })
  })

  it('в рейсе без перевозчика нет договора-заявки', async () => {
    loggedIn(tripRoutes(makeTrip({ carrier: null, carrier_name: null })))
    renderApp('/trips')
    await userEvent.click(await screen.findByRole('button', { name: 'ORD-2026-00005-1' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByRole('button', { name: 'CMR' })
    expect(within(dialog).queryByRole('button', { name: 'Договор-заявка перевозчику' })).not.toBeInTheDocument()
  })

  it('в карточке клиента при правке есть «Договор», при создании нет', async () => {
    const client = {
      id: 7, name: 'ТОО Ромашка', bin_iin: '', type: null, type_name: '', status: 'active', credit_limit: '0', orders_count: 0, notes: '',
      contacts: [], created_at: '2026-10-01T05:00:00Z',
    }
    const m = loggedIn([
      ['GET', /^\/api\/clients\/\?/, { body: page([client]) }],
      caps(true),
      ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ number: 'Д-1', kind: 'contract' }) }],
    ])
    renderApp('/clients')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый клиент' }))[0]!)
    expect(within(await screen.findByRole('dialog')).queryByRole('button', { name: 'Договор' })).not.toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' }))
    await userEvent.click(await screen.findByRole('button', { name: 'ТОО Ромашка' }))
    await userEvent.click(await within(await screen.findByRole('dialog')).findByRole('button', { name: 'Договор' }))
    await screen.findByText('Документ Д-1 выдан')
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'contract', client: 7 })
  })
})
