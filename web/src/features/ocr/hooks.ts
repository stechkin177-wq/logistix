import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteOcrDocument, getOcrSettings, reviewOcrDocument, listOcrDocuments, saveOcrSettings, testGemini, testOcrSettings, getGeminiModels, updateOcrDocument, uploadOcrDocument, type OcrFilters,
} from './api'
import type { OcrDocType } from './types'

export const useOcrDocuments = (f: OcrFilters) =>
  useQuery({ queryKey: ['ocr', 'documents', f], queryFn: ({ signal }) => listOcrDocuments(f, signal), placeholderData: keepPreviousData })
export const useOcrSettings = () => useQuery({ queryKey: ['ocr', 'settings'], queryFn: ({ signal }) => getOcrSettings(signal) })

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
export function useSaveOcrSettings() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: saveOcrSettings, onSuccess: invalidate })
}
export const useTestOcrSettings = () => useMutation({ mutationFn: testOcrSettings })
export const useTestGemini = () => useMutation({ mutationFn: testGemini })
export function useReviewOcr() {
  const invalidate = useInvalidateOcr()
  return useMutation({ mutationFn: ({ id, reviewed }: { id: number; reviewed: boolean }) => reviewOcrDocument(id, reviewed), onSuccess: invalidate })
}
export const useGeminiModels = () => useMutation({ mutationFn: getGeminiModels })
