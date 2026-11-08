import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { Driver, DriverDocument, DriverListParams, DriverPayload } from './types'

export const listDrivers = (p: DriverListParams, signal?: AbortSignal) =>
  api.get<Paginated<Driver>>('/drivers/', { q: p.q, status: p.status, ordering: p.ordering, page: p.page, page_size: p.pageSize }, { signal })

export const getDriver = (id: number, signal?: AbortSignal) => api.get<Driver>(`/drivers/${String(id)}/`, undefined, { signal })
export const createDriver = (body: DriverPayload) => api.post<Driver>('/drivers/', body)
export const updateDriver = (id: number, body: DriverPayload) => api.patch<Driver>(`/drivers/${String(id)}/`, body)
export const deleteDriver = (id: number) => api.delete(`/drivers/${String(id)}/`)

export const createDriverDocument = (body: Partial<DriverDocument>) => api.post<DriverDocument>('/driver-documents/', body)
export const deleteDriverDocument = (id: number) => api.delete(`/driver-documents/${String(id)}/`)
