import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createDriver, createDriverDocument, deleteDriver, deleteDriverDocument, getDriver, listDrivers, updateDriver } from './api'
import type { DriverDocument, DriverListParams, DriverPayload } from './types'

export function useDriverList(params: DriverListParams) {
  return useQuery({
    queryKey: ['drivers', 'list', params],
    queryFn: ({ signal }) => listDrivers(params, signal),
    placeholderData: keepPreviousData,
  })
}

export function useDriver(id: number | null) {
  return useQuery({
    queryKey: ['drivers', 'one', id],
    queryFn: ({ signal }) => getDriver(id as number, signal),
    enabled: id !== null,
  })
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['drivers'] })
}

export function useSaveDriver() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: DriverPayload }) => (id === null ? createDriver(body) : updateDriver(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteDriver() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => deleteDriver(id), onSuccess: invalidate })
}

export function useAddDriverDocument() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (body: Partial<DriverDocument>) => createDriverDocument(body), onSuccess: invalidate })
}

export function useDeleteDriverDocument() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => deleteDriverDocument(id), onSuccess: invalidate })
}
