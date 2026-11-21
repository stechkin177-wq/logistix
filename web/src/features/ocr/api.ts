import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { GeminiTestResult, OcrDocType, OcrDocument, OcrFieldKey, OcrSettings, OcrSettingsForm, OcrTestResult } from './types'

export interface OcrFilters { page: number; q?: string; status?: string; doc_type?: string }
export const listOcrDocuments = (f: OcrFilters, signal?: AbortSignal) =>
  api.get<Paginated<OcrDocument>>('/ocr/documents/', { page: f.page, q: f.q || undefined, status: f.status || undefined, doc_type: f.doc_type || undefined }, { signal })
export const uploadOcrDocument = (file: Blob, name: string, docType: OcrDocType) => {
  const form = new FormData()
  form.append('file', file, name)
  form.append('doc_type', docType)
  return api.upload<OcrDocument>('/ocr/documents/', form)
}
export const updateOcrDocument = (id: number, body: { doc_type?: OcrDocType; fields?: Partial<Record<OcrFieldKey, string>> }) =>
  api.patch<OcrDocument>(`/ocr/documents/${String(id)}/`, body)
export const reviewOcrDocument = (id: number, reviewed: boolean) => api.post<OcrDocument>(`/ocr/documents/${String(id)}/review/`, { reviewed })
export const deleteOcrDocument = (id: number) => api.delete(`/ocr/documents/${String(id)}/`)
export const getOcrFileUrl = (id: number) => api.get<{ url: string }>(`/ocr/documents/${String(id)}/file/`)

export const getOcrSettings = (signal?: AbortSignal) => api.get<OcrSettings>('/ocr/settings/', undefined, { signal })
export const saveOcrSettings = (body: Partial<OcrSettingsForm>) => api.put<OcrSettings>('/ocr/settings/', body)
export const testOcrSettings = () => api.post<{ results: OcrTestResult }>('/ocr/settings/test/', {})
export const testGemini = () => api.post<GeminiTestResult>('/ocr/settings/test-gemini/', {})
