import { api } from '../../shared/api/client'
import type { DocSubject, DocumentType, DocumentTypePayload } from './types'

export const listDocumentTypes = (subject: DocSubject, archived: boolean, signal?: AbortSignal) =>
  api.get<DocumentType[]>('/document-types/', { subject, archived: archived ? '1' : undefined }, { signal })
export const createDocumentType = (body: DocumentTypePayload) => api.post<DocumentType>('/document-types/', body)
export const updateDocumentType = (id: number, body: DocumentTypePayload) => api.patch<DocumentType>(`/document-types/${String(id)}/`, body)
export const archiveDocumentType = (id: number) => api.post<DocumentType>(`/document-types/${String(id)}/archive/`)
export const unarchiveDocumentType = (id: number) => api.post<DocumentType>(`/document-types/${String(id)}/unarchive/`)
