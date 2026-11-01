import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page } from '../../test/fixtures'
import { makeRate } from '../../test/finance'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { CURRENCIES, handbookBody } from '../../test/orders'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const common = [
  ['GET', '/api/handbooks/?code=currency', { body: handbookBody('currency', CURRENCIES) }],
] as MockRoutes

const ratesRoute = (rates = [makeRate()]): MockRoutes[number] => ['GET', /^\/api\/finance\/rates\//, { body: page(rates) }]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Финансы: оболочка', () => {
  it('показывает вкладки раздела, «Курсы» открывается по адресу', async () => {
    loggedIn([ratesRoute(), ...common])
    renderApp('/finance?tab=rates')
    expect(await screen.findByRole('tab', { name: 'Курсы' })).toHaveAttribute('aria-selected', 'true')
  })

  it('без права finance.view страница недоступна', async () => {
    loggedIn([ratesRoute(), ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.view') } })
    renderApp('/finance')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})

describe('Финансы: курсы', () => {
  it('выводит курсы и пустое состояние', async () => {
    loggedIn([ratesRoute(), ...common])
    renderApp('/finance?tab=rates')
    const table = await screen.findByRole('table')
    const row = (await within(table).findByText('USD')).closest('tr')!
    expect(within(row).getByText(/450,5/)).toBeInTheDocument()
  })

  it('пустой список показывает подсказку', async () => {
    loggedIn([ratesRoute([]), ...common])
    renderApp('/finance?tab=rates')
    expect(await screen.findByText('Курсов пока нет')).toBeInTheDocument()
  })

  it('добавляет курс: POST с валютой, датой и значением; тенге в списке валют нет', async () => {
    const m = loggedIn([
      ratesRoute([]),
      ['POST', '/api/finance/rates/', { status: 201, body: makeRate({ id: 2 }) }],
      ...common,
    ])
    const user = userEvent.setup()
    renderApp('/finance?tab=rates')
    await user.click(await screen.findByRole('button', { name: 'Добавить курс' }))
    const dialog = await screen.findByRole('dialog')
    const select = within(dialog).getByLabelText(/^Валюта/)
    expect(within(select).queryByRole('option', { name: /KZT|Тенге/ })).not.toBeInTheDocument()
    await user.selectOptions(select, '12')
    await user.type(within(dialog).getByLabelText(/^Дата/), '2026-10-05')
    await user.type(within(dialog).getByLabelText(/^Курс к тенге/), '455.25')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ currency: 12, date: '2026-10-05', rate: '455.25' })
    })
  })

  it('ошибка сервера «курс на дату уже задан» показывается у поля даты', async () => {
    loggedIn([
      ratesRoute([]),
      ['POST', '/api/finance/rates/', { status: 400, body: { date: ['Курс на эту дату уже задан'] } }],
      ...common,
    ])
    const user = userEvent.setup()
    renderApp('/finance?tab=rates')
    await user.click(await screen.findByRole('button', { name: 'Добавить курс' }))
    const dialog = await screen.findByRole('dialog')
    await user.selectOptions(within(dialog).getByLabelText(/^Валюта/), '12')
    await user.type(within(dialog).getByLabelText(/^Дата/), '2026-10-05')
    await user.type(within(dialog).getByLabelText(/^Курс к тенге/), '455')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Курс на эту дату уже задан')).toBeInTheDocument()
  })

  it('кнопка добавления отключена без finance.create', async () => {
    loggedIn([ratesRoute(), ...common], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.create') } })
    renderApp('/finance?tab=rates')
    expect(await screen.findByRole('button', { name: 'Добавить курс' })).toBeDisabled()
  })
})
