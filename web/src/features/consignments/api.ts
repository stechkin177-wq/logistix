import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { Consignment, ConsignmentListParams } from './types'

export function listConsignments(p: ConsignmentListParams, signal?: AbortSignal) {
  return api.get<Paginated<Consignment>>(
    '/consignments/',
    { q: p.q, client: p.client, without_trip: p.withoutTrip ? 1 : undefined, page: p.page, page_size: p.pageSize },
    { signal },
  )
}
