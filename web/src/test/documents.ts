import type { DocTemplate, IssuedDocument } from '../features/documents/types'

export function makeTemplate(over: Partial<DocTemplate> = {}): DocTemplate {
  return {
    id: 1, kind: 'contract', name: 'Договор', language: 'ru', is_active: true, versions_count: 1,
    current_version: { id: 11, number: 1, sha256: 'x', is_starter: true, uploaded_by: null, created_at: '2026-11-01T05:00:00Z' },
    ...over,
  }
}

export function makeIssued(over: Partial<IssuedDocument> = {}): IssuedDocument {
  return {
    id: 1, kind: 'act', number: 'АКТ-2026-00001', issue_date: '2026-11-02', language: 'ru',
    client: { id: 7, name: 'ТОО Ромашка' }, order: null, trip: null, invoice: { id: 3, number: 'СЧ-2026-00003' },
    template_version: { id: 11, number: 1, template: 1 }, created_by: { id: 1, full_name: 'Админ Админов' },
    created_at: '2026-11-02T05:00:00Z', ...over,
  }
}
