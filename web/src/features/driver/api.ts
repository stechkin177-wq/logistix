import { api } from '../../shared/api/client'
import type { DriverAction, DriverMe, DriverScope, DriverTrip, DriverTripDetail } from './types'

export const getDriverMe = (signal?: AbortSignal) => api.get<DriverMe>('/driver/me/', undefined, { signal })
export const listDriverTrips = (scope: DriverScope, signal?: AbortSignal) =>
  api.get<{ results: DriverTrip[] }>('/driver/trips/', { scope }, { signal })
export const getDriverTrip = (id: number, signal?: AbortSignal) => api.get<DriverTripDetail>(`/driver/trips/${String(id)}/`, undefined, { signal })
export const doTripAction = (id: number, body: { action: DriverAction; vehicle_km?: number; trailer_km?: number }) =>
  api.post<DriverTripDetail>(`/driver/trips/${String(id)}/action/`, body)
