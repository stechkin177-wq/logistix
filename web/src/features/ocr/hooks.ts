import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  archiveOcrDocument, createOcrDocType, deleteOcrDocType, deleteOcrDocument, getOcrImage, getOcrSettings, listOcrDocTypes, listOcrDocuments,
  listOcrGroups, reviewOcrDocument, saveOcrReview, saveOcrSettings, testOcrSettings, updateOcrDocType, updateOcrDocument, uploadOcrDocument, type OcrFilters,
} from './api'
import type { OcrDocType } from './types'

export const useOcrDocuments = (f: OcrFilters, enabled = true) =>
  useQuery({ queryKey: ['ocr', 'documents', f], queryFn: ({ signal }) => listOcrDocuments(f, signal), placeholderData: keepPreviousData, enabled })
export const useOcrGroups = (by: 'driver' | 'vehicle', archived: boolean, enabled = true) =>
  useQuery({ queryKey: ['ocr', 'groups', by, archived], queryFn: ({ signal }) => listOcrGroups(by, archived, signal), enabled })
export const useOcrSettings = () => useQuery({ queryKey: ['ocr', 'settings'], queryFn: ({ signal }) => getOcrSettings(signal) })
export const useOcrDocTypes = () => useQuery({ queryKey: ['ocr', 'doc-types'], queryFn: ({ signal }) => listOcrDocTypes(signal) })
export const useOcrImage = (id: number | null) => useQuery({ queryKey: ['ocr', 'image', id], queryFn: () => getOcrImage(id as number), enabled: id !== null, staleTime: 5 * 60_000, retry: false })

function useInvalidateOcr() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['ocr'] })
}
export function useUploadOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ file, name, docType }: { file: Blob; name: string; docType: OcrDocType }) => uploadOcrDocument(file, name, docType), onSuccess: invalidate })
}
export function useUpdateOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof updateOcrDocument>[1] }) => updateOcrDocument(id, body), onSuccess: invalidate })
}
export function useDeleteOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: deleteOcrDocument, onSuccess: invalidate })
}
export function useArchiveOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, archived }: { id: number; archived: boolean }) => archiveOcrDocument(id, archived), onSuccess: invalidate })
}
export function useReviewOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, reviewed }: { id: number; reviewed: boolean }) => reviewOcrDocument(id, reviewed), onSuccess: invalidate })
}
export function useSaveOcrReview() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, review, done }: { id: number; review: Parameters<typeof saveOcrReview>[1]; done: boolean }) => saveOcrReview(id, review, done), onSuccess: invalidate })
}
export function useSaveOcrSettings() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: saveOcrSettings, onSuccess: invalidate })
}
export const useTestOcrSettings = () => useMutation({ mutationFn: testOcrSettings })
export function useCreateOcrDocType() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: createOcrDocType, onSuccess: invalidate })
}
export function useUpdateOcrDocType() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof updateOcrDocType>[1] }) => updateOcrDocType(id, body), onSuccess: invalidate })
}
export function useDeleteOcrDocType() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: deleteOcrDocType, onSuccess: invalidate })
}
