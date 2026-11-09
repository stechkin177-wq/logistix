import { api } from '../../shared/api/client'
import type { ComboOption } from '../../shared/ui/Combobox'
import type { Paginated } from '../../shared/ui/Pagination'
import type { Party } from '../parties/types'
import type { Trip, TripCreatePayload, TripListParams, TripPatchPayload } from './types'

export function listTrips(p: TripListParams, signal?: AbortSignal) {
  return api.get<Paginated<Trip>>(
    '/trips/',
    {
      q: p.q,
      order: p.order,
      status: p.status,
      carrier: p.carrier,
      only_consolidated: p.consolidated ? 1 : undefined,
      page: p.page,
      page_size: p.pageSize,
    },
    { signal },
  )
}

export const getTrip = (id: number, signal?: AbortSignal) => api.get<Trip>(`/trips/${String(id)}/`, undefined, { signal })

export const createTrip = (body: TripCreatePayload) => api.post<Trip>('/trips/', body)

export const patchTrip = (id: number, body: TripPatchPayload) => api.patch<Trip>(`/trips/${String(id)}/`, body)

/** reason - причина выхода из «Завершён» (нужна только для такого перехода). */
export interface TripStatusExtra {
  reason?: string
  /** Официальный пробег (необязательно): только при выезде в рейс и при завершении. */
  vehicle_km?: number
  trailer_km?: number
}

export const changeTripStatus = (id: number, status: number, extra: TripStatusExtra = {}) =>
  api.post<Trip>(`/trips/${String(id)}/status/`, { status, ...extra })

export const reassignTrip = (id: number, consignmentIds: number[]) =>
  api.post<Trip>(`/trips/${String(id)}/reassign/`, { consignment_ids: consignmentIds })

export const deleteTrip = (id: number) => api.delete(`/trips/${String(id)}/`)

/** Активные перевозчики для выбора в рейсе (сервер принимает только активных). */
export async function searchActiveCarriers(q: string, signal: AbortSignal): Promise<ComboOption[]> {
  const page = await api.get<Paginated<Party>>('/carriers/', { q, status: 'active', page_size: 20, ordering: 'name' }, { signal })
  return page.results.map((p) => ({ id: p.id, label: p.name }))
}
