import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteDriverReport, doTripAction, getDriverMe, getDriverTrip, listDriverReports, listDriverTrips, sendDriverReport } from './api'
import type { OcrDocType } from '../ocr/types'
import type { DriverAction, DriverScope } from './types'

export const useDriverMe = () => useQuery({ queryKey: ['driver', 'me'], queryFn: ({ signal }) => getDriverMe(signal) })
export const useDriverTrips = (scope: DriverScope) =>
  useQuery({ queryKey: ['driver', 'trips', scope], queryFn: ({ signal }) => listDriverTrips(scope, signal), placeholderData: keepPreviousData })
export const useDriverTrip = (id: number) => useQuery({ queryKey: ['driver', 'trip', id], queryFn: ({ signal }) => getDriverTrip(id, signal) })

export function useTripAction(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { action: DriverAction; vehicle_km?: number; engine_hours?: number }) => doTripAction(id, body),
    onSuccess: (trip) => {
      qc.setQueryData(['driver', 'trip', id], trip)
      void qc.invalidateQueries({ queryKey: ['driver', 'trips'] })
    },
  })
}

export const useDriverReports = () => useQuery({ queryKey: ['driver', 'reports'], queryFn: ({ signal }) => listDriverReports(signal) })
export function useSendReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, name, docType, trip }: { file: Blob; name: string; docType: OcrDocType; trip: number | null }) => sendDriverReport(file, name, docType, trip),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['driver', 'reports'] }),
  })
}
export function useDeleteReport() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: deleteDriverReport, onSuccess: () => qc.invalidateQueries({ queryKey: ['driver', 'reports'] }) })
}
