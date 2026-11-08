import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createChild, createVehicle, deleteChild, deleteVehicle, getFuelStats, getMileageCheck, getReminders, listChild,
  listVehicles, updateVehicle,
} from './api'
import type { VehicleListParams, VehiclePayload } from './types'

export function useVehicleList(params: VehicleListParams) {
  return useQuery({
    queryKey: ['fleet', 'vehicles', params],
    queryFn: ({ signal }) => listVehicles(params, signal),
    placeholderData: keepPreviousData,
  })
}

export const useReminders = () =>
  useQuery({ queryKey: ['fleet', 'reminders'], queryFn: ({ signal }) => getReminders(signal) })

export const useMileageCheck = (id: number, enabled: boolean) =>
  useQuery({ queryKey: ['fleet', 'mileage-check', id], queryFn: ({ signal }) => getMileageCheck(id, signal), enabled })

export const useFuelStats = (id: number) =>
  useQuery({ queryKey: ['fleet', 'fuel-stats', id], queryFn: ({ signal }) => getFuelStats(id, signal) })

export function useChildList<T>(path: string, vehicle: number) {
  return useQuery({ queryKey: ['fleet', 'child', path, vehicle], queryFn: ({ signal }) => listChild<T>(path, vehicle, signal) })
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['fleet'] })
}

export function useSaveVehicle() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: VehiclePayload }) => (id === null ? createVehicle(body) : updateVehicle(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteVehicle() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => deleteVehicle(id), onSuccess: invalidate })
}

export function useCreateChild(path: string) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (body: Record<string, unknown>) => createChild(path, body), onSuccess: invalidate })
}

export function useDeleteChild(path: string) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => deleteChild(path, id), onSuccess: invalidate })
}
