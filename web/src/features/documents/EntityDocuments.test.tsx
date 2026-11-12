import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderWithProviders } from '../../test/renderApp'
import { EntityDocuments } from './EntityDocuments'

const doc = { id: 1, kind: 'order_request', number: 'З-1', issue_date: '2026-11-02', language: 'ru', client: null, order: { id: 5, number: 'ORD-5' }, trip: null, invoice: null, template_version: { id: 1, number: 1, template: 1 }, created_by: null }

describe('Документы записи', () => {
  it('запрашивает выданные документы по заказу и показывает их со скачиванием', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/documents\/issued\/\?/, { body: page([doc]) }],
      ['GET', '/api/documents/capabilities/', { body: { pdf_available: false } }],
    ])
    renderWithProviders(<EntityDocuments source={{ order: 5 }} />)
    expect(await screen.findByText('З-1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /DOCX/ })).toBeInTheDocument()
    const q = new URL(m.calls.find((c) => c.path.startsWith('/api/documents/issued/'))!.path, 'http://x').searchParams
    expect(q.get('order')).toBe('5')
  })

  it('пустой список - подсказка; без права documents.view список не запрашивается', async () => {
    loggedIn([['GET', /^\/api\/documents\/issued\/\?/, { body: page([]) }]])
    const first = renderWithProviders(<EntityDocuments source={{ trip: 9 }} />)
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument()
    first.unmount()
    const m = loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.view') } })
    renderWithProviders(<EntityDocuments source={{ trip: 9 }} />)
    expect(await screen.findByText('Список выданных документов недоступен')).toBeInTheDocument()
    expect(m.calls.some((c) => c.path.startsWith('/api/documents/issued/'))).toBe(false)
  })
})
