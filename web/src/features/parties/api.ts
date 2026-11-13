import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { ComboOption } from '../../shared/ui/Combobox'
import type { Party, PartyKind, PartyListParams, PartyPayload } from './types'

export function listParties(kind: PartyKind, p: PartyListParams, signal?: AbortSignal) {
  return api.get<Paginated<Party>>(
    `/${kind}/`,
    { q: p.q, type: p.type, status: p.status, ordering: p.ordering, page: p.page, page_size: p.pageSize },
    { signal },
  )
}

export const createParty = (kind: PartyKind, body: PartyPayload) => api.post<Party>(`/${kind}/`, body)

export const updateParty = (kind: PartyKind, id: number, body: PartyPayload) =>
  api.patch<Party>(`/${kind}/${id}/`, body)

export const deleteParty = (kind: PartyKind, id: number) => api.delete(`/${kind}/${id}/`)

/** Поиск для Combobox (заказ, фильтры): первые 20 по названию/БИН. */
export async function searchParties(kind: PartyKind, q: string, signal: AbortSignal, status?: 'active'): Promise<ComboOption[]> {
  const page = await api.get<Paginated<Party>>(`/${kind}/`, { q, page_size: 20, ordering: 'name', status }, { signal })
  return page.results.map((p) => ({ id: p.id, label: p.name }))
}

export function getParty(kind: PartyKind, id: number, signal?: AbortSignal) {
  return api.get<Party>(`/${kind}/${id}/`, undefined, { signal })
}
