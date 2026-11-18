import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { Geofence, GeofenceEvent, GeofencePayload, GpsAccount, GpsAccountForm, GpsUnit, SyncResult, TrackResult } from './types'

export const getGpsAccount = (signal?: AbortSignal) => api.get<GpsAccount>('/gps/account/', undefined, { signal })
export const saveGpsAccount = (body: Partial<GpsAccountForm>) => api.put<GpsAccount>('/gps/account/', body)
export const testGpsAccount = () => api.post<{ ok: boolean; user?: string; units?: number; error?: string }>('/gps/account/test/', {})
export const syncGps = () => api.post<SyncResult>('/gps/sync/', {})

export interface UnitFilters { page: number; q?: string; linked?: string }
export const listGpsUnits = (f: UnitFilters, signal?: AbortSignal) =>
  api.get<Paginated<GpsUnit>>('/gps/units/', { page: f.page, q: f.q || undefined, linked: f.linked || undefined }, { signal })
export const linkGpsUnit = (id: number, vehicle: number) => api.post<GpsUnit>(`/gps/units/${String(id)}/link/`, { vehicle })
export const unlinkGpsUnit = (id: number) => api.post<GpsUnit>(`/gps/units/${String(id)}/unlink/`, {})
export const autoLinkGpsUnits = () => api.post<{ linked: number }>('/gps/units/auto-link/', {})

export const listGeofences = (page: number, q: string, signal?: AbortSignal) =>
  api.get<Paginated<Geofence>>('/gps/geofences/', { page, q: q || undefined }, { signal })
export const createGeofence = (body: GeofencePayload) => api.post<Geofence>('/gps/geofences/', body)
export const updateGeofence = (id: number, body: Partial<GeofencePayload>) => api.patch<Geofence>(`/gps/geofences/${String(id)}/`, body)
export const deleteGeofence = (id: number) => api.delete(`/gps/geofences/${String(id)}/`)

export interface EventFilters { page: number; event_type?: string; vehicle?: number; geofence?: number }
export const listGeofenceEvents = (f: EventFilters, signal?: AbortSignal) =>
  api.get<Paginated<GeofenceEvent>>('/gps/events/', { page: f.page, event_type: f.event_type || undefined, vehicle: f.vehicle, geofence: f.geofence }, { signal })

export const getUnitTrack = (id: number, dateFrom: string, dateTo: string, signal?: AbortSignal) =>
  api.get<TrackResult>(`/gps/units/${String(id)}/track/`, { date_from: dateFrom || undefined, date_to: dateTo || undefined }, { signal })
