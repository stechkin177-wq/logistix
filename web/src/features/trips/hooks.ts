import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changeTripStatus, createTrip, deleteTrip, getTrip, listTrips, patchTrip, reassignTrip } from './api'
import type { TripCreatePayload, TripListParams, TripPatchPayload } from './types'

export function useTripList(params: TripListParams) {
  return useQuery({
    queryKey: ['trips', 'list', params],
    queryFn: ({ signal }) => listTrips(params, signal),
    placeholderData: keepPreviousData,
  })
}

export function useTrip(id: number | null) {
  return useQuery({
    queryKey: ['trips', 'detail', id],
    queryFn: ({ signal }) => getTrip(id ?? 0, signal),
    enabled: id !== null,
  })
}

/** Рейсы меняют очередь грузов, вкладку «Рейсы» заказов и счётчики грузов. */
export function useInvalidateTrips() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['trips'] }),
      qc.invalidateQueries({ queryKey: ['consignments'] }),
      qc.invalidateQueries({ queryKey: ['orders'] }),
      qc.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
}

export function useCreateTrip() {
  const invalidate = useInvalidateTrips()
  return useMutation({ mutationFn: (body: TripCreatePayload) => createTrip(body), onSuccess: invalidate })
}

export function usePatchTrip() {
  const invalidate = useInvalidateTrips()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: TripPatchPayload }) => patchTrip(id, body), onSuccess: invalidate })
}

export function useChangeTripStatus() {
  const invalidate = useInvalidateTrips()
  return useMutation({ mutationFn: ({ id, status, reason }: { id: number; status: number; reason?: string }) => changeTripStatus(id, status, reason), onSuccess: invalidate })
}

export function useReassignTrip() {
  const invalidate = useInvalidateTrips()
  return useMutation({ mutationFn: ({ id, ids }: { id: number; ids: number[] }) => reassignTrip(id, ids), onSuccess: invalidate })
}

export function useDeleteTrip() {
  const invalidate = useInvalidateTrips()
  return useMutation({ mutationFn: (id: number) => deleteTrip(id), onSuccess: invalidate })
}
