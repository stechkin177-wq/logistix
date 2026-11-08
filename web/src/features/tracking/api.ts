import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { CargoTransfer, ConsignmentEvent, EventType, TransferListParams, TransferPayload } from './types'

export const listEvents = (consignment: number, signal?: AbortSignal) =>
  api.get<ConsignmentEvent[]>(`/consignments/${String(consignment)}/events/`, undefined, { signal })

export const createEvent = (consignment: number, body: { event_type: EventType; stop: number; note?: string }) =>
  api.post<ConsignmentEvent>(`/consignments/${String(consignment)}/events/`, body)

export const listConsignmentTransfers = (consignment: number, signal?: AbortSignal) =>
  api.get<CargoTransfer[]>(`/consignments/${String(consignment)}/transfers/`, undefined, { signal })

export const createTransfer = (consignment: number, body: TransferPayload) =>
  api.post<CargoTransfer>(`/consignments/${String(consignment)}/transfers/`, body)

export function listTransfers(p: TransferListParams, signal?: AbortSignal) {
  return api.get<Paginated<CargoTransfer>>(
    '/transfers/',
    {
      consignment: p.consignment ?? undefined,
      status: p.status || undefined,
      kind: p.kind || undefined,
      pending: p.pending ? 1 : undefined,
      page: p.page,
      page_size: p.pageSize,
    },
    { signal },
  )
}

export const confirmTransfer = (id: number) => api.post<CargoTransfer>(`/transfers/${String(id)}/confirm/`, {})

export const reverseTransfer = (id: number, note?: string) =>
  api.post<CargoTransfer>(`/transfers/${String(id)}/reverse/`, note ? { note } : {})
