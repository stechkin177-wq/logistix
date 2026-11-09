import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { archiveDocumentType, createDocumentType, listDocumentTypes, unarchiveDocumentType, updateDocumentType } from './api'
import type { DocSubject, DocumentTypePayload } from './types'

const KEY = ['document-types'] as const

export const useDocumentTypes = (subject: DocSubject, archived = false, enabled = true) =>
  useQuery({ queryKey: [...KEY, subject, archived], queryFn: ({ signal }) => listDocumentTypes(subject, archived, signal), enabled })

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: KEY })
}

export function useSaveDocumentType() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: DocumentTypePayload }) => (id === null ? createDocumentType(body) : updateDocumentType(id, body)),
    onSuccess: invalidate,
  })
}

export function useArchiveDocumentType() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, archive }: { id: number; archive: boolean }) => (archive ? archiveDocumentType(id) : unarchiveDocumentType(id)),
    onSuccess: invalidate,
  })
}
