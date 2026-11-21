import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { OcrDocType, OcrDocTypeRow, OcrDocument, OcrFieldKey, OcrGroup, OcrSettings, OcrSettingsForm, OcrTestResult, ReviewData } from './types'

export interface OcrFilters {
  page: number
  q?: string
  status?: string
  doc_type?: string
  /** id водителя или машины; 0 - документы без привязки */
  driver?: number
  vehicle?: number
  archived?: boolean
  reviewed?: boolean
}
export const listOcrDocuments = (f: OcrFilters, signal?: AbortSignal) =>
  api.get<Paginated<OcrDocument>>('/ocr/documents/', {
    page: f.page, q: f.q || undefined, status: f.status || undefined, doc_type: f.doc_type || undefined,
    driver: f.driver, vehicle: f.vehicle, archived: f.archived ? 'true' : undefined,
    reviewed: f.reviewed === undefined ? undefined : String(f.reviewed),
  }, { signal })
export const listOcrGroups = (by: 'driver' | 'vehicle', archived: boolean, signal?: AbortSignal) =>
  api.get<{ results: OcrGroup[] }>('/ocr/documents/groups/', { by, archived: archived ? 'true' : undefined }, { signal })
export const uploadOcrDocument = (file: Blob, name: string, docType: OcrDocType) => {
  const form = new FormData()
  form.append('file', file, name)
  form.append('doc_type', docType)
  return api.upload<OcrDocument>('/ocr/documents/', form)
}
export const updateOcrDocument = (id: number, body: { doc_type?: OcrDocType; fields?: Partial<Record<OcrFieldKey, string>> }) =>
  api.patch<OcrDocument>(`/ocr/documents/${String(id)}/`, body)
export const reviewOcrDocument = (id: number, reviewed: boolean) => api.post<OcrDocument>(`/ocr/documents/${String(id)}/review/`, { reviewed })
export const archiveOcrDocument = (id: number, archived: boolean) => api.post<OcrDocument>(`/ocr/documents/${String(id)}/archive/`, { archived })
export const saveOcrReview = (id: number, review: ReviewData, done: boolean) =>
  api.post<OcrDocument>(`/ocr/documents/${String(id)}/save-review/`, { ...review, done })
export const deleteOcrDocument = (id: number) => api.delete(`/ocr/documents/${String(id)}/`)
/** Фото документа (ответ - картинка, нужен токен, поэтому грузится как blob). */
export const getOcrImage = async (id: number) => (await api.download(`/ocr/documents/${String(id)}/image/`)).blob

export const listOcrDocTypes = (signal?: AbortSignal) => api.get<OcrDocTypeRow[]>('/ocr/doc-types/', undefined, { signal })
export const createOcrDocType = (body: Pick<OcrDocTypeRow, 'name' | 'handler' | 'driver_visible'>) => api.post<OcrDocTypeRow>('/ocr/doc-types/', body)
export const updateOcrDocType = (id: number, body: Partial<Pick<OcrDocTypeRow, 'name' | 'handler' | 'driver_visible' | 'is_active'>>) =>
  api.patch<OcrDocTypeRow>(`/ocr/doc-types/${String(id)}/`, body)
export const deleteOcrDocType = (id: number) => api.delete<{ deactivated: boolean } | undefined>(`/ocr/doc-types/${String(id)}/`)

export const getOcrSettings = (signal?: AbortSignal) => api.get<OcrSettings>('/ocr/settings/', undefined, { signal })
export const saveOcrSettings = (body: Partial<OcrSettingsForm>) => api.put<OcrSettings>('/ocr/settings/', body)
export const testOcrSettings = () => api.post<{ results: OcrTestResult }>('/ocr/settings/test/', {})
