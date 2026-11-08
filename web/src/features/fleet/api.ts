import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { FuelStats, MileageCheck, Reminder, Vehicle, VehicleListParams, VehiclePayload } from './types'

export const listVehicles = (p: VehicleListParams, signal?: AbortSignal) =>
  api.get<Paginated<Vehicle>>('/vehicles/', { q: p.q, kind: p.kind, status: p.status, ordering: p.ordering, page: p.page, page_size: p.pageSize }, { signal })
export const createVehicle = (body: VehiclePayload) => api.post<Vehicle>('/vehicles/', body)
export const updateVehicle = (id: number, body: VehiclePayload) => api.patch<Vehicle>(`/vehicles/${String(id)}/`, body)
export const deleteVehicle = (id: number) => api.delete(`/vehicles/${String(id)}/`)
export const getReminders = (signal?: AbortSignal) => api.get<{ count: number; results: Reminder[] }>('/fleet/reminders/', undefined, { signal })
export const getMileageCheck = (id: number, signal?: AbortSignal) => api.get<MileageCheck>(`/vehicles/${String(id)}/mileage-check/`, undefined, { signal })
export const getFuelStats = (id: number, signal?: AbortSignal) => api.get<FuelStats>(`/vehicles/${String(id)}/fuel-stats/`, undefined, { signal })

/** Записи карточки техники (документы, страховки, обслуживание, заправки, пробег): список по технике. */
export const listChild = <T,>(path: string, vehicle: number, signal?: AbortSignal) =>
  api.get<Paginated<T>>(`/${path}/`, { vehicle, page_size: 100 }, { signal })
export const createChild = (path: string, body: Record<string, unknown>) => api.post<unknown>(`/${path}/`, body)
export const deleteChild = (path: string, id: number) => api.delete(`/${path}/${String(id)}/`)
