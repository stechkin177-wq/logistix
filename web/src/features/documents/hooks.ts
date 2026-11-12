import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getCapabilities, issueDocument, listIssued, listPlaceholders, listTemplates, patchTemplate, resetTemplate,
  uploadTemplateVersion,
} from './api'
import type { DocumentKind, IssuedFilters, IssuePayload } from './types'

export function useTemplates() {
  return useQuery({ queryKey: ['documents', 'templates'], queryFn: ({ signal }) => listTemplates(signal) })
}

function useInvalidateTemplates() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['documents', 'templates'] })
}

export function useUploadVersion() {
  const invalidate = useInvalidateTemplates()
  return useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => uploadTemplateVersion(id, file),
    onSuccess: invalidate,
  })
}

export function useResetTemplate() {
  const invalidate = useInvalidateTemplates()
  return useMutation({ mutationFn: (id: number) => resetTemplate(id), onSuccess: invalidate })
}

export function usePatchTemplate() {
  const invalidate = useInvalidateTemplates()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; is_active?: boolean } }) => patchTemplate(id, body),
    onSuccess: invalidate,
  })
}

export function usePlaceholders(kind: DocumentKind | null) {
  return useQuery({
    queryKey: ['documents', 'placeholders', kind],
    queryFn: ({ signal }) => listPlaceholders(kind as DocumentKind, signal),
    enabled: kind !== null,
    staleTime: 5 * 60_000,
  })
}

export function useIssued(filters: IssuedFilters, enabled = true) {
  return useQuery({
    queryKey: ['documents', 'issued', filters],
    queryFn: ({ signal }) => listIssued(filters, signal),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useIssueDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: IssuePayload) => issueDocument(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', 'issued'] }),
  })
}

export function useCapabilities() {
  return useQuery({
    queryKey: ['documents', 'capabilities'],
    queryFn: ({ signal }) => getCapabilities(signal),
    staleTime: 5 * 60_000,
  })
}
