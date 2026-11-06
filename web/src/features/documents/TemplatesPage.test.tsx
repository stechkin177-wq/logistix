import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeTemplate } from '../../test/documents'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

const list = (templates = [makeTemplate()]): MockRoutes[number] => ['GET', '/api/documents/templates/', { body: templates }]
const URL_ = '/settings/document-templates'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Шаблоны документов', () => {
  it('выводит вид, название, язык, версию и метку «стартовая»', async () => {
    loggedIn([list([makeTemplate(), makeTemplate({ id: 2, kind: 'act', name: 'Акт', current_version: { id: 12, number: 3, sha256: 'y', is_starter: false, uploaded_by: { id: 1, full_name: 'А' }, created_at: '2026-11-02T05:00:00Z' } })])])
    renderApp(URL_)
    const table = await screen.findByRole('table')
    const first = (await within(table).findByText('v1')).closest('tr')!
    expect(within(first).getByText('стартовая')).toBeInTheDocument()
    expect(within(first).getByText('Русский')).toBeInTheDocument()
    const second = within(table).getByText('v3').closest('tr')!
    expect(within(second).queryByText('стартовая')).not.toBeInTheDocument()
  })

  it('загрузка файла отправляет FormData на versions/', async () => {
    const m = loggedIn([list(), ['POST', '/api/documents/templates/1/versions/', { status: 201, body: makeTemplate() }]])
    renderApp(URL_)
    const input = await screen.findByLabelText('Файл новой версии: Договор')
    const file = new File(['x'], 'new.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    await userEvent.upload(input, file)
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST')).toBe(true) })
    const body = m.calls.find((c) => c.method === 'POST')!.body
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBeInstanceOf(File)
    expect(await screen.findByText(/Новая версия шаблона «Договор» загружена/)).toBeInTheDocument()
  })

  it('ошибка template_invalid без detail показывается переводом', async () => {
    loggedIn([list(), ['POST', '/api/documents/templates/1/versions/', { status: 400, body: { detail: '', code: 'template_invalid' } }]])
    renderApp(URL_)
    const input = await screen.findByLabelText('Файл новой версии: Договор')
    await userEvent.upload(input, new File(['x'], 'bad.docx'))
    expect(await screen.findByText(/Файл шаблона не подходит/)).toBeInTheDocument()
  })

  it('без documents.update кнопки загрузки и возврата отключены', async () => {
    loggedIn([list()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.update') } })
    renderApp(URL_)
    expect(await screen.findByRole('button', { name: 'Загрузить новую версию' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Вернуть стартовую версию: Договор/ })).toBeDisabled()
  })

  it('«Метки» открывает окно со справочником меток вида', async () => {
    const m = loggedIn([
      list(),
      ['GET', '/api/documents/templates/placeholders/?kind=contract', { body: [{ name: 'client.name', description: 'Название клиента' }] }],
    ])
    renderApp(URL_)
    await userEvent.click(await screen.findByRole('button', { name: /Метки шаблона: Договор/ }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Название клиента')).toBeInTheDocument()
    expect(within(dialog).getByText('{{ client.name }}')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path === '/api/documents/templates/placeholders/?kind=contract')).toBe(true)
  })

  it('скачивание использует авторизованный запрос и имя из Content-Disposition', async () => {
    const created: Blob[] = []
    URL.createObjectURL = vi.fn((b: Blob | MediaSource) => { created.push(b as Blob); return 'blob:x' })
    URL.revokeObjectURL = vi.fn()
    const names: string[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download) })
    const m = loggedIn([
      list(),
      ['GET', '/api/documents/templates/1/download/', { body: 'x', headers: { 'Content-Disposition': 'attachment; filename="contract-ru.docx"; filename*=UTF-8\'\'%D0%B4%D0%BE%D0%B3.docx' } }],
    ])
    renderApp(URL_)
    await userEvent.click(await screen.findByRole('button', { name: /Скачать текущий шаблон: Договор/ }))
    await waitFor(() => { expect(names).toEqual(['дог.docx']) })
    expect(m.calls.find((c) => c.path === '/api/documents/templates/1/download/')?.headers.Authorization).toBe('Bearer a')
    click.mockRestore()
  })

  it('отключение отправляет is_active=false; включение требует documents.update', async () => {
    const m = loggedIn([list(), ['PATCH', '/api/documents/templates/1/', { body: makeTemplate({ is_active: false }) }]])
    renderApp(URL_)
    await userEvent.click(await screen.findByRole('button', { name: /Отключить шаблон: Договор/ }))
    await waitFor(() => { expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ is_active: false }) })
  })

  it('без documents.delete отключить нельзя', async () => {
    loggedIn([list()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.delete') } })
    renderApp(URL_)
    expect(await screen.findByRole('button', { name: /Отключить шаблон: Договор/ })).toBeDisabled()
  })

  it('возврат стартовой версии просит подтверждение и вызывает reset/', async () => {
    const m = loggedIn([list(), ['POST', '/api/documents/templates/1/reset/', { body: makeTemplate() }]])
    renderApp(URL_)
    await userEvent.click(await screen.findByRole('button', { name: /Вернуть стартовую версию: Договор/ }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Вернуть стартовую' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST' && c.path.endsWith('/reset/'))).toBe(true) })
  })

  it('без documents.view страница недоступна', async () => {
    loggedIn([list()], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.view') } })
    renderApp(URL_)
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
