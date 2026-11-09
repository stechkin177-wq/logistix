import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const MODULES = ['logistics', 'drivers', 'documents']
const DRIVER = {
  id: 5, full_name: 'Сериков Ерлан', phone: '+77001112233', iin: '', birth_date: null, license_number: 'KZ-77',
  license_categories: 'C,E', license_expires: '2027-01-01', status: 'active', user: null, notes: '',
  documents: [{ id: 9, driver: 5, kind: 'medical', number: 'M-1', issued_at: null, expires_at: '2026-12-01', notes: '' }],
  created_at: '2026-10-01T05:00:00Z', updated_at: '2026-10-01T05:00:00Z',
}

describe('Водители', () => {
  it('меню и список: строка водителя, статус и удостоверение', async () => {
    loggedIn([['GET', /^\/api\/drivers\/\?/, { body: page([DRIVER]) }]], { session: { modules: MODULES } })
    renderApp('/drivers')
    expect(await screen.findByText('Сериков Ерлан')).toBeInTheDocument()
    expect(screen.getByText('KZ-77 · C,E')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Работает')).toBeInTheDocument()
  })

  it('создание: ФИО обязательно, телефон уходит как введён, ошибка сервера показывается у поля', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/drivers\/\?/, { body: page([]) }],
        ['POST', '/api/drivers/', { status: 400, body: { iin: ['Водитель с таким ИИН уже есть'] } }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/drivers')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый водитель' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByText('Обязательное поле')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    await userEvent.type(within(drawer).getByLabelText(/ФИО/), 'Новый Водитель')
    await userEvent.type(within(drawer).getByLabelText('ИИН'), '123456789012')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByText('Водитель с таким ИИН уже есть')).toBeInTheDocument()
    expect(m.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ full_name: 'Новый Водитель', iin: '123456789012' })
  })

  it('карточка: документы водителя и справка через общую систему документов', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/drivers\/\?/, { body: page([DRIVER]) }],
        ['GET', /^\/api\/document-types\//, { body: [{ id: 3, subject: 'driver', name: 'Водительское удостоверение', fields: ['number', 'issued_by', 'issued_at', 'expires_at', 'comment'], required: [], extra: [], remind: true, remind_days: [30], is_active: true, archived_at: null, sort_order: 0 }] }],
        ['POST', '/api/driver-documents/', { status: 201, body: { id: 10 } }],
        ['POST', '/api/documents/issued/', { status: 201, body: { id: 77, kind: 'letter', number: '', issue_date: '2026-11-08', language: 'ru', client: null, order: null, trip: null, invoice: null } }],
      ],
      { session: { modules: MODULES } },
    )
    renderApp('/drivers')
    await userEvent.click(await screen.findByRole('button', { name: 'Сериков Ерлан' }))
    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByText(/Медицинская справка M-1/)).toBeInTheDocument()
    await userEvent.type(within(drawer).getByLabelText('Номер'), 'L-5')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Добавить документ' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/driver-documents/' && c.method === 'POST') ).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/driver-documents/')!.body).toMatchObject({ driver: 5, doc_type: 3, number: 'L-5' })
    await userEvent.click(within(drawer).getByRole('button', { name: 'Справка о водителе' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/documents/issued/') ).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/documents/issued/')!.body).toMatchObject({ kind: 'letter', subject_type: 'drivers.driver', subject_id: 5 })
  })

  it('без модуля drivers пункта меню нет', async () => {
    loggedIn([], { session: { modules: ['logistics'] } })
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByText('Водители')).not.toBeInTheDocument()
  })
})
