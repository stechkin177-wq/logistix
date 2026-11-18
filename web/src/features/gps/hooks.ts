import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  autoLinkGpsUnits, createGeofence, deleteGeofence, getGpsAccount, getUnitTrack, linkGpsUnit, listGeofenceEvents, listGeofences, listGpsUnits,
  saveGpsAccount, syncGps, testGpsAccount, unlinkGpsUnit, updateGeofence, type EventFilters, type UnitFilters,
} from './api'

export const useGpsAccount = () => useQuery({ queryKey: ['gps', 'account'], queryFn: ({ signal }) => getGpsAccount(signal) })
export const useGpsUnits = (f: UnitFilters) =>
  useQuery({ queryKey: ['gps', 'units', f], queryFn: ({ signal }) => listGpsUnits(f, signal), placeholderData: keepPreviousData })
export const useGeofences = (page: number, q: string) =>
  useQuery({ queryKey: ['gps', 'geofences', page, q], queryFn: ({ signal }) => listGeofences(page, q, signal), placeholderData: keepPreviousData })
export const useGeofenceEvents = (f: EventFilters) =>
  useQuery({ queryKey: ['gps', 'events', f], queryFn: ({ signal }) => listGeofenceEvents(f, signal), placeholderData: keepPreviousData })

function useInvalidateGps() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['gps'] })
}

export function useSaveGpsAccount() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: saveGpsAccount, onSuccess: invalidate })
}
export const useTestGpsAccount = () => useMutation({ mutationFn: testGpsAccount })
export function useSyncGps() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: syncGps, onSuccess: invalidate })
}
export function useLinkUnit() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: ({ id, vehicle }: { id: number; vehicle: number }) => linkGpsUnit(id, vehicle), onSuccess: invalidate })
}
export function useUnlinkUnit() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: unlinkGpsUnit, onSuccess: invalidate })
}
export function useAutoLinkUnits() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: autoLinkGpsUnits, onSuccess: invalidate })
}
export function useSaveGeofence() {
  const invalidate = useInvalidateGps()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: Parameters<typeof createGeofence>[0] }) => (id === null ? createGeofence(body) : updateGeofence(id, body)),
    onSuccess: invalidate,
  })
}
export function useDeleteGeofence() {
  const invalidate = useInvalidateGps()
  return useMutation({ mutationFn: deleteGeofence, onSuccess: invalidate })
}

/** Трек юнита за период; запрашивается только по нажатию «Показать» (enabled). */
export const useUnitTrack = (id: number | null, dateFrom: string, dateTo: string, enabled: boolean) =>
  useQuery({
    queryKey: ['gps', 'track', id, dateFrom, dateTo],
    queryFn: ({ signal }) => getUnitTrack(id ?? 0, dateFrom, dateTo, signal),
    enabled: enabled && id !== null,
    staleTime: 60_000,
  })
