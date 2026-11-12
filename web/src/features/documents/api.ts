import { api } from '../../shared/api/client'
import { safeFilename } from '../../shared/api/filename'
import { saveBlob } from '../../shared/api/saveBlob'
import type { Paginated } from '../../shared/ui/Pagination'
import type {
  Capabilities, DocTemplate, DocumentKind, FileFormat, IssuedDocument, IssuedFilters, IssuePayload, Placeholder,
} from './types'

export const listTemplates = (signal?: AbortSignal) => api.get<DocTemplate[]>('/documents/templates/', undefined, { signal })
export function uploadTemplateVersion(templateId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api.upload<DocTemplate>(`/documents/templates/${String(templateId)}/versions/`, form)
}
export const downloadTemplate = (templateId: number) => api.download(`/documents/templates/${String(templateId)}/download/`)
export const resetTemplate = (templateId: number) => api.post<DocTemplate>(`/documents/templates/${String(templateId)}/reset/`, {})
export const patchTemplate = (templateId: number, body: { name?: string; is_active?: boolean }) =>
  api.patch<DocTemplate>(`/documents/templates/${String(templateId)}/`, body)
export const listPlaceholders = (kind: DocumentKind, signal?: AbortSignal) =>
  api.get<Placeholder[]>('/documents/templates/placeholders/', { kind }, { signal })

export const listIssued = (f: IssuedFilters, signal?: AbortSignal) =>
  api.get<Paginated<IssuedDocument>>(
    '/documents/issued/',
    {
      order: f.order,
      trip: f.trip,
      client: f.client,
      kind: f.kind || undefined,
      date_from: f.date_from || undefined,
      date_to: f.date_to || undefined,
      search: f.search || undefined,
      page: f.page,
      page_size: f.pageSize,
    },
    { signal },
  )
export const issueDocument = (body: IssuePayload) => api.post<IssuedDocument>('/documents/issued/', body)
export const downloadIssued = (issuedId: number, format: FileFormat) =>
  api.download(`/documents/issued/${String(issuedId)}/download/`, { format })
export const getCapabilities = (signal?: AbortSignal) => api.get<Capabilities>('/documents/capabilities/', undefined, { signal })

/** Скачивание с авторизацией: имя файла берётся из Content-Disposition ответа. */
export async function saveDownloaded(request: Promise<{ blob: Blob; filename: string | null }>, fallback: string): Promise<void> {
  const { blob, filename } = await request
  saveBlob(blob, safeFilename(filename, fallback))
}
