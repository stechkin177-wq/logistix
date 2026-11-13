import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const CLIENT = {
  id: 7, name: 'ТОО Ромашка', bin_iin: '', type: null, type_name: null, status: 'active', credit_limit: '0', orders_count: 0,
  notes: '', address: 'г. Астана', bank: 'Halyk', iban: 'KZ1', accounts: [], contacts: [], created_at: '2026-10-01T05:00:00Z',
}
const ACCOUNT = { id: 1, client: 7, carrier: null, legal_entity: null, bank: 'Halyk', bic: 'HSBKKZKX', iban: 'KZ1', kbe: '17', currency: 'KZT', is_default: true, note: '', created_at: '2026-10-01T05:00:00Z' }
const CONTRACT = { id: 3, client: 7, carrier: null, party_name: 'ТОО Ромашка', kind: 'main', number: 'Д-1', date: '2026-01-10', valid_until: null, title: '', comment: '', source: 'manual', is_expired: false, in_use: false, created_at: '2026-01-10T00:00:00Z' }
const base: MockRoutes = [
  ['GET', '/api/clients/7/', { body: CLIENT }],
  ['GET', /^\/api\/handbooks\/\?code=client_type/, { body: { code: 'client_type', name: 'x', group: 'g', values: [] } }],
]

describe('Банковские счета в карточке', () => {
  it('вкладка «Реквизиты»: адрес в форме, счета отдельным блоком; добавление счёта шлёт POST с владельцем', async () => {
    const m = loggedIn([
      ...base,
      ['GET', /^\/api\/bank-accounts\/\?/, { body: [ACCOUNT] }],
      ['POST', '/api/bank-accounts/', { status: 201, body: { ...ACCOUNT, id: 2, iban: 'KZ2', is_default: false } }],
    ])
    renderApp('/clients/7?tab=requisites')
    expect(await screen.findByLabelText('Адрес')).toHaveValue('г. Астана')
    expect(await screen.findByText('Halyk')).toBeInTheDocument()
    expect(screen.getByText('по умолчанию')).toBeInTheDocument()
    expect(screen.queryByLabelText('IBAN')).not.toBeInTheDocument() // поля банка из формы карточки убраны
    await userEvent.click(screen.getByRole('button', { name: 'Добавить счёт' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('IBAN'), 'KZ2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path === '/api/bank-accounts/')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ client: 7, iban: 'KZ2' })
  })

  it('сохранение карточки не отправляет bank/iban (иначе затёрло бы счета)', async () => {
    const m = loggedIn([...base, ['GET', /^\/api\/bank-accounts\/\?/, { body: [ACCOUNT] }], ['PATCH', '/api/clients/7/', { body: CLIENT }]])
    renderApp('/clients/7')
    await userEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'PATCH')!.body as Record<string, unknown>
    expect(body).not.toHaveProperty('bank')
    expect(body).not.toHaveProperty('iban')
  })

  it('ошибка сервера по IBAN показывается у поля; без права изменения кнопок нет', async () => {
    loggedIn([
      ...base,
      ['GET', /^\/api\/bank-accounts\/\?/, { body: [] }],
      ['POST', '/api/bank-accounts/', { status: 400, body: { iban: ['Такой счёт у владельца уже есть'] } }],
    ])
    renderApp('/clients/7?tab=requisites')
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить счёт' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('IBAN'), 'KZ1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Такой счёт у владельца уже есть')).toBeInTheDocument()
  })

  it('без clients.update счета только для чтения', async () => {
    loggedIn([...base, ['GET', /^\/api\/bank-accounts\/\?/, { body: [ACCOUNT] }]], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'clients.update') } })
    renderApp('/clients/7?tab=requisites')
    await screen.findByText('Halyk')
    expect(screen.getByRole('button', { name: 'Добавить счёт' })).toBeDisabled()
  })
})

describe('Договоры в карточке и выбор в заказе', () => {
  it('вкладка «Договоры»: реестр и создание с датой', async () => {
    const m = loggedIn([
      ...base,
      ['GET', /^\/api\/contracts\/\?/, { body: page([CONTRACT]) }],
      ['POST', '/api/contracts/', { status: 201, body: { ...CONTRACT, id: 4, number: 'Д-2' } }],
    ])
    renderApp('/clients/7?tab=contracts')
    expect(await screen.findByText('Д-1')).toBeInTheDocument()
    expect(screen.getByText(/бессрочно/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить договор' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Номер/), 'Д-2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findAllByText('Обязательное поле')).not.toHaveLength(0) // дата не указана
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('удаление договора, выбранного в заказах, показывает отказ сервера', async () => {
    loggedIn([
      ...base,
      ['GET', /^\/api\/contracts\/\?/, { body: page([{ ...CONTRACT, in_use: true }]) }],
      ['DELETE', '/api/contracts/3/', { status: 409, body: { detail: 'Договор выбран в заказах или рейсах и не может быть удалён', code: 'contract_in_use' } }],
    ])
    renderApp('/clients/7?tab=contracts')
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить договор Д-1' }))
    const confirm = await screen.findByRole('alertdialog')
    await userEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    expect(await within(confirm).findByText(/не может быть удалён/)).toBeInTheDocument()
  })
})
