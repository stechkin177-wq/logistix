import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeIssued } from '../../test/documents'
import { page } from '../../test/fixtures'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const caps = (pdf: boolean): MockRoutes[number] => ['GET', '/api/documents/capabilities/', { body: { pdf_available: pdf } }]
const issuedList = (rows = [makeIssued()]): MockRoutes[number] => ['GET', /^\/api\/documents\/issued\/\?/, { body: page(rows) }]

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Журнал документов', () => {
  it('выводит номера и ссылки на источники', async () => {
    loggedIn([issuedList([makeIssued(), makeIssued({ id: 2, kind: 'order_request', number: 'ЗК-1', invoice: null, client: null, order: { id: 5, number: 'ORD-5' } })]), caps(true)])
    renderApp('/documents')
    const table = await screen.findByRole('table')
    const row = (await within(table).findByText('АКТ-2026-00001')).closest('tr')!
    expect(within(row).getByRole('link', { name: 'СЧ-2026-00003' })).toHaveAttribute('href', '/finance/invoices/3')
    expect(within(row).getByText('Акт')).toBeInTheDocument()
    const second = within(table).getByText('ЗК-1').closest('tr')!
    expect(within(second).getByRole('link', { name: 'ORD-5' })).toHaveAttribute('href', '/orders/5')
  })

  it('кнопка PDF скрыта при pdf_available=false и видна при true', async () => {
    loggedIn([issuedList(), caps(false)])
    const first = renderApp('/documents')
    expect(await screen.findByRole('button', { name: /Скачать DOCX/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Скачать PDF/ })).not.toBeInTheDocument()
    first.unmount()
    vi.unstubAllGlobals()
    loggedIn([issuedList(), caps(true)])
    renderApp('/documents')
    expect(await screen.findByRole('button', { name: /Скачать PDF/ })).toBeInTheDocument()
  })

  it('скачивание вызывает нужный URL с форматом', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const m = loggedIn([
      issuedList(), caps(true),
      ['GET', /^\/api\/documents\/issued\/1\/download\//, { body: 'x', headers: { 'Content-Disposition': 'attachment; filename="act.pdf"' } }],
    ])
    renderApp('/documents')
    await userEvent.click(await screen.findByRole('button', { name: /Скачать PDF/ }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/documents/issued/1/download/?format=pdf')).toBe(true) })
    await userEvent.click(screen.getByRole('button', { name: /Скачать DOCX/ }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/documents/issued/1/download/?format=docx')).toBe(true) })
  })

  it('фильтры уходят в запрос и хранятся в адресе', async () => {
    const m = loggedIn([issuedList(), caps(true)])
    renderApp('/documents?kind=act&date_from=2026-11-01&date_to=2026-11-30&search=АКТ')
    await screen.findByText('АКТ-2026-00001')
    const call = m.calls.find((c) => c.path.startsWith('/api/documents/issued/?'))!
    const params = new URL(call.path, 'http://x').searchParams
    expect(params.get('kind')).toBe('act')
    expect(params.get('date_from')).toBe('2026-11-01')
    expect(params.get('date_to')).toBe('2026-11-30')
    expect(params.get('search')).toBe('АКТ')
  })

  it('смена вида записывается в адрес', async () => {
    loggedIn([issuedList(), caps(true)])
    const { router } = renderApp('/documents')
    await userEvent.selectOptions(await screen.findByLabelText('Вид'), 'cmr')
    await waitFor(() => { expect(router.state.location.search).toContain('kind=cmr') })
  })
})

describe('Письмо на бланке', () => {
  const open = async () => {
    await userEvent.click(await screen.findByRole('button', { name: 'Письмо на бланке' }))
    return screen.findByRole('dialog')
  }
  const fill = async (dialog: HTMLElement, body = 'Текст') => {
    await userEvent.type(within(dialog).getByLabelText(/^Адресат/), 'ТОО Ромашка')
    await userEvent.type(within(dialog).getByLabelText(/^Тема/), 'Уведомление')
    const area = within(dialog).getByLabelText(/^Текст письма/)
    await userEvent.click(area)
    await userEvent.paste(body)
  }

  it('отправляет letter и показывает диалог «Документ выдан»', async () => {
    const m = loggedIn([
      issuedList(), caps(true),
      ['POST', '/api/documents/issued/', { status: 201, body: makeIssued({ id: 9, kind: 'letter', number: 'ПИС-1', invoice: null, client: null }) }],
    ])
    renderApp('/documents')
    const dialog = await open()
    await fill(dialog)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Выдать письмо' }))
    await waitFor(() => {
      expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({
        kind: 'letter', letter: { recipient: 'ТОО Ромашка', subject: 'Уведомление', body: 'Текст' },
      })
    })
    expect(await screen.findByText('Документ ПИС-1 выдан')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Скачать PDF/ }).length).toBeGreaterThan(0)
  })

  it('пустые тема и текст блокируют отправку', async () => {
    const m = loggedIn([issuedList(), caps(true)])
    renderApp('/documents')
    const dialog = await open()
    await userEvent.type(within(dialog).getByLabelText(/^Адресат/), 'ТОО')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Выдать письмо' }))
    expect(await within(dialog).findAllByText('Обязательное поле')).toHaveLength(2)
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('текст длиннее 20 000 символов показывает ошибку и не отправляется', async () => {
    const m = loggedIn([issuedList(), caps(true)])
    renderApp('/documents')
    const dialog = await open()
    await fill(dialog, 'я'.repeat(20001))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Выдать письмо' }))
    expect(await within(dialog).findByText('Не длиннее 20000 символов')).toBeInTheDocument()
    expect(m.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('ошибка template_missing показана переводом', async () => {
    loggedIn([
      issuedList(), caps(true),
      ['POST', '/api/documents/issued/', { status: 400, body: { detail: 'raw', code: 'template_missing' } }],
    ])
    renderApp('/documents')
    const dialog = await open()
    await fill(dialog)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Выдать письмо' }))
    expect(await within(dialog).findByText(/нет активного шаблона/)).toBeInTheDocument()
  })

  it('без documents.create кнопка письма отключена', async () => {
    loggedIn([issuedList(), caps(true)], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.create') } })
    renderApp('/documents')
    expect(await screen.findByRole('button', { name: 'Письмо на бланке' })).toBeDisabled()
  })
})
