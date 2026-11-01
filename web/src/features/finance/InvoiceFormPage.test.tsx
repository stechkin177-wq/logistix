import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { VAT_RATES, makeInvoice } from '../../test/finance'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody, makeLine, makeOrder } from '../../test/orders'
import { makeTrip } from '../../test/trips'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const hb = [
  ['GET', '/api/handbooks/?code=vat_rate', { body: handbookBody('vat_rate', VAT_RATES) }],
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
] as MockRoutes

const LINES = [
  makeLine(),
  makeLine({ id: 101, title: 'Погрузка', category: 'Услуги', income: '50000.00', is_base: false }),
  makeLine({ id: 102, title: 'Расход', income: '0.00', expense: '10.00', is_base: false }),
]
const orderRoutes = [
  ['GET', '/api/orders/5/', { body: makeOrder() }],
  ['GET', /^\/api\/order-lines\/\?order=5/, { body: page(LINES) }],
] as MockRoutes

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Счёт клиенту: форма', () => {
  it('предлагает строки дохода, считает итоги при выборе строки и ставки НДС', async () => {
    loggedIn([...orderRoutes, ...hb])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?order=5')
    expect(await screen.findByLabelText('Включить строку Начальная ставка')).toBeInTheDocument()
    expect(screen.queryByLabelText('Включить строку Расход')).not.toBeInTheDocument() // без дохода
    await user.click(screen.getByLabelText('Включить строку Начальная ставка'))
    await user.selectOptions(screen.getByLabelText(/^Ставка НДС/), '34')
    const totals = screen.getByRole('group', { name: 'Итоги' })
    expect(within(totals).getAllByText(/250\s000,00/)).not.toHaveLength(0)
    expect(within(totals).getByText(/40\s000,00/)).toBeInTheDocument()
    expect(within(totals).getByText(/290\s000,00/)).toBeInTheDocument()
  })

  it('сохраняет черновик: POST с заказом, клиентом, валютой, ставкой и позициями', async () => {
    const m = loggedIn([
      ...orderRoutes, ...hb,
      ['POST', '/api/finance/invoices/', { status: 201, body: makeInvoice({ id: 21, status: 'draft', display_status: 'draft', number: '' }) }],
      ['GET', '/api/finance/invoices/21/', { body: makeInvoice({ id: 21, status: 'draft', display_status: 'draft', number: '' }) }],
      ['GET', /^\/api\/finance\/invoices\/21\/payments\//, { body: page([]) }],
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?order=5')
    await user.click(await screen.findByLabelText('Включить строку Погрузка'))
    await user.selectOptions(screen.getByLabelText(/^Ставка НДС/), '31')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({
        direction: 'out', party: 7, order: 5, currency: 11, vat_rate: 31,
        items: [{ title: 'Погрузка', amount_net: '50000.00', line: 101 }],
      })
    })
    expect(await screen.findByRole('heading', { name: /Черновик №21/ })).toBeInTheDocument()
  })

  it('без выбранных строк и ставки НДС не отправляет запрос и показывает ошибки', async () => {
    const m = loggedIn([...orderRoutes, ...hb])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?order=5')
    await user.click(await screen.findByRole('button', { name: 'Сохранить черновик' }))
    expect(await screen.findByText('Выберите хотя бы одну строку')).toBeInTheDocument()
    expect(screen.getByText('Выберите ставку НДС')).toBeInTheDocument()
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('неверная сумма позиции блокирует сохранение', async () => {
    const m = loggedIn([...orderRoutes, ...hb])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?order=5')
    await user.click(await screen.findByLabelText('Включить строку Погрузка'))
    await user.selectOptions(screen.getByLabelText(/^Ставка НДС/), '31')
    const amount = screen.getByLabelText('Сумма без НДС: Погрузка')
    await user.clear(amount)
    await user.type(amount, '12,5x')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    expect(await screen.findByText('Введите число')).toBeInTheDocument()
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('ошибка сервера «строка уже в другом счёте» показывается пользователю', async () => {
    loggedIn([
      ...orderRoutes, ...hb,
      ['POST', '/api/finance/invoices/', { status: 400, body: { detail: 'x', code: 'item_already_invoiced' } }],
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?order=5')
    await user.click(await screen.findByLabelText('Включить строку Погрузка'))
    await user.selectOptions(screen.getByLabelText(/^Ставка НДС/), '31')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    expect(await screen.findByText('Строка заказа уже включена в другой счёт')).toBeInTheDocument()
  })

  it('кнопка сохранения отключена без finance.create', async () => {
    loggedIn([...orderRoutes, ...hb], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.create') } })
    renderApp('/finance/invoices/new?order=5')
    expect(await screen.findByRole('button', { name: 'Сохранить черновик' })).toBeDisabled()
  })
})

describe('Правка черновика', () => {
  it('предзаполняет позиции и отправляет PATCH', async () => {
    const draft = makeInvoice({ id: 4, status: 'draft', display_status: 'draft', number: '', items: [{ id: 1, title: 'Начальная ставка', amount_net: '1000.00', line: 100 }] })
    const m = loggedIn([
      ['GET', '/api/finance/invoices/4/', { body: draft }],
      ['PATCH', '/api/finance/invoices/4/', { body: draft }],
      ...orderRoutes, ...hb,
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/4/edit')
    const include = await screen.findByLabelText('Включить строку Начальная ставка')
    await waitFor(() => { expect(include).toBeChecked() })
    expect(screen.getByLabelText('Сумма без НДС: Начальная ставка')).toHaveValue('1000.00')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
        order: 5, vat_rate: 34, items: [{ title: 'Начальная ставка', amount_net: '1000.00', line: 100 }],
      })
    })
  })

  it('выставленный счёт править нельзя', async () => {
    loggedIn([['GET', '/api/finance/invoices/1/', { body: makeInvoice() }], ...orderRoutes, ...hb])
    renderApp('/finance/invoices/1/edit')
    expect(await screen.findByText(/Выставленный счёт нельзя менять/)).toBeInTheDocument()
  })
})

describe('Счёт перевозчика: форма', () => {
  const tripRoutes = [
    ['GET', '/api/trips/90/', { body: makeTrip() }],
    ['GET', /^\/api\/order-lines\/\?order=5/, { body: page([makeLine(), makeLine({ id: 103, title: 'Перевозка', income: '0.00', expense: '80000.00', is_base: false })]) }],
  ] as MockRoutes

  it('по рейсу показывает строки расхода и отправляет счёт перевозчика', async () => {
    const m = loggedIn([
      ...tripRoutes, ...hb,
      ['POST', '/api/finance/invoices/', { status: 201, body: makeInvoice({ id: 30, direction: 'in', status: 'draft', display_status: 'draft', number: '' }) }],
      ['GET', '/api/finance/invoices/30/', { body: makeInvoice({ id: 30, direction: 'in', status: 'draft', display_status: 'draft', number: '' }) }],
      ['GET', /^\/api\/finance\/invoices\/30\/payments\//, { body: page([]) }],
    ])
    const user = userEvent.setup()
    renderApp('/finance/invoices/new?direction=in&trip=90')
    await user.click(await screen.findByLabelText('Включить строку Перевозка'))
    await user.selectOptions(screen.getByLabelText(/^Ставка НДС/), '31')
    await user.type(screen.getByLabelText('Номер у перевозчика'), 'К-77')
    await user.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({
        direction: 'in', party: 6, trip: 90, currency: 11, vat_rate: 31, external_number: 'К-77',
        items: [{ title: 'Перевозка', amount_net: '80000.00', line: 103 }],
      })
    })
  })

  it('если у заказов рейса нет расхода, предлагает создать его из цены рейса', async () => {
    loggedIn([
      ['GET', '/api/trips/90/', { body: makeTrip() }],
      ['GET', /^\/api\/order-lines\/\?order=5/, { body: page([makeLine()]) }],
      ...hb,
    ])
    renderApp('/finance/invoices/new?direction=in&trip=90')
    expect(await screen.findByText(/создайте расход из цены рейса/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Создать расход из цены рейса' })).toBeEnabled()
  })
})
